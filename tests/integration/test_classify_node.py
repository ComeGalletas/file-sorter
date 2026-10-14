"""CLS-002.2: the classify node on synthetic images with replayed vision output (acceptance).

The scenario is `classify_support.run_classify`: four benign synthetic pictures, the seeded
DESIGN §4.3 prompts, and the SigLIP and NSFW answers recorded under `tests/recordings/graph/`
by the gpu recorder (`tests/gpu/graph/test_record_classify.py`, TST-008.D3). Nothing here
loads a model.

The expected rows are computed independently of the node: the same replay backend scores each
decoded working copy through `score_images`, then CLS-002.1's `nsfw_branch` and `choose` decide.
The adult cases use `NumericGate`, a thin double over the replay that returns plain numbers for
`nsfw_scores` and nothing else: no content is made or described, because flat pictures never
score as adult on the real gate (lead ruling, #99).
"""

import numpy as np
import psycopg
import pytest

from classifier.graph.classify import (
    WORKING_COPY_UNREADABLE,
    ClassifyResult,
    _load_categories,
    classify,
    open_working_copy,
)
from classifier.graph.nodes import Node, NodeContext
from classifier.graph.run import run
from classifier.models.classify_rules import choose, nsfw_branch
from classifier.models.vision import score_images
from tests.integration.classify_support import (
    LABELS,
    make_config,
    run_classify,
    seed_rows,
    source_hash,
)

pytestmark = pytest.mark.usefixtures("empty_ledger")  # TST-003.1


class NumericGate:
    """The replay for embeddings and parameters; `nsfw_scores` returns the given numbers."""

    def __init__(self, replay, score: float) -> None:
        self._replay = replay
        self._score = score

    def __getattr__(self, name: str):
        return getattr(self._replay, name)

    def nsfw_scores(self, images) -> np.ndarray:
        return np.full(len(images), self._score, dtype=np.float32)


def _backend(vision_backend):
    from classifier.config import load_config

    models = load_config().models
    return vision_backend("graph", models.classifier, models.nsfw)


def _rows(dsn: str) -> dict[str, dict[str, object]]:
    with psycopg.connect(dsn) as conn:
        cursor = conn.execute(
            "select source_hash, status, branch, nsfw_score, format, topic, format_scores,"
            " topic_scores, needs_review, review_reason, image_vec::text, error from files"
        )
        names = [c.name for c in cursor.description]
        return {r[0]: dict(zip(names, r, strict=True)) for r in cursor.fetchall()}


def _expected(dsn, backend, results, config, source_hash_: str, nsfw_override=None):
    """The row the node must write, from the pure functions and the same replay."""
    with psycopg.connect(dsn) as conn:
        rules, prompts = _load_categories(conn)
    image = open_working_copy(results / ".work", source_hash_, "png")
    per_category = score_images(
        backend, [image], prompts.texts, prompts.category_ids, mode=config.classify.score
    )[0]
    by_id = {str(rule.id): rule for rule in rules}
    axes: dict[str, dict[str, float]] = {"format": {}, "topic": {}}
    for category_id, value in per_category.items():
        axes[by_id[category_id].axis][by_id[category_id].name] = value
    nsfw = float(backend.nsfw_scores([image])[0]) if nsfw_override is None else nsfw_override
    branch = nsfw_branch(nsfw, config.nsfw.threshold)
    return branch, nsfw, choose(axes["format"], axes["topic"], rules, branch, config.classify)


def _check_rows(dsn, backend, results, config, rows, nsfw_override=None) -> None:
    for label in LABELS:
        digest = source_hash(label)
        branch, nsfw, choice = _expected(dsn, backend, results, config, digest, nsfw_override)
        row = rows[digest]
        assert row["status"] == "classified"  # D12: a dry run stops here
        assert (row["branch"], row["format"], row["topic"]) == (branch, choice.format, choice.topic)
        assert row["nsfw_score"] == pytest.approx(nsfw, abs=1e-6)
        assert (row["needs_review"], row["review_reason"]) == (
            choice.needs_review,
            choice.review_reason,
        )
        assert row["format_scores"] == choice.format_top
        assert row["topic_scores"] == choice.topic_top
        assert len(row["format_scores"]) <= 5 and len(row["topic_scores"]) <= 5  # D5
        assert row["error"] is None


def test_every_sanitized_row_is_classified_as_the_pure_rules_decide(
    schema_dsn: str, tmp_path, vision_backend
) -> None:
    backend = _backend(vision_backend)
    result, config = run_classify(schema_dsn, tmp_path, backend)
    rows = _rows(schema_dsn)
    assert len(rows) == len(LABELS)
    _check_rows(schema_dsn, backend, tmp_path / "results", config, rows)
    unsorted = sum(r["format"] == "unsorted" for r in rows.values())
    no_topic = sum(r["topic"] is None for r in rows.values())
    assert result == ClassifyResult(
        classified=len(LABELS), unsorted=unsorted, no_topic=no_topic, adult=0
    )
    assert all(r["needs_review"] == (r["format"] == "unsorted") for r in rows.values())
    # Not vacuous: the test thresholds let both axes pick a winner somewhere (see classify_support).
    assert any(r["format"] != "unsorted" for r in rows.values())
    assert any(r["topic"] is not None for r in rows.values())


def test_the_stored_vector_is_the_recorded_embedding(
    schema_dsn: str, tmp_path, vision_backend
) -> None:  # CLS-002.D10
    backend = _backend(vision_backend)
    run_classify(schema_dsn, tmp_path, backend)
    rows = _rows(schema_dsn)
    for label in LABELS:
        digest = source_hash(label)
        image = open_working_copy(tmp_path / "results" / ".work", digest, "png")
        stored = np.array(rows[digest]["image_vec"].strip("[]").split(","), dtype=np.float32)
        assert stored.shape == (1152,)
        np.testing.assert_allclose(stored, backend.embed_images([image])[0], atol=1e-6)


def test_a_numeric_gate_above_the_threshold_sends_every_row_to_the_adult_branch(
    schema_dsn: str, tmp_path, vision_backend
) -> None:
    gate = NumericGate(_backend(vision_backend), 0.99)
    result, config = run_classify(schema_dsn, tmp_path, gate)
    rows = _rows(schema_dsn)
    _check_rows(schema_dsn, gate, tmp_path / "results", config, rows, nsfw_override=0.99)
    assert all(r["branch"] == "nsfw" for r in rows.values())
    assert result.adult == len(LABELS) and result.classified == len(LABELS)
    # R-CLS-6: a `safe` category never wins for an adult image; the rest fall back to unsorted.
    with psycopg.connect(schema_dsn) as conn:
        safe_only = {
            n for (n,) in conn.execute("select name from categories where branch = 'safe'")
        }
    assert not ({r["format"] for r in rows.values()} & (safe_only - {"unsorted"}))


def test_a_rerun_changes_nothing_and_asks_the_models_for_nothing(
    schema_dsn: str, tmp_path, vision_backend
) -> None:
    backend = _backend(vision_backend)
    run_classify(schema_dsn, tmp_path, backend)
    before = _rows(schema_dsn)
    with psycopg.connect(schema_dsn) as conn:
        ctx = NodeContext(tmp_path / "source", True, tmp_path / "results", make_config())
        # No vision on the context: a re-run must not even build the real backend.
        assert classify(conn, ctx) == ClassifyResult()
        conn.commit()
    assert _rows(schema_dsn) == before


def test_one_unreadable_copy_errors_alone_and_the_rest_are_classified(
    schema_dsn: str, tmp_path, vision_backend
) -> None:  # CLS-002.D7
    backend = _backend(vision_backend)
    results = tmp_path / "results"
    config = make_config()
    (tmp_path / "source").mkdir()
    with psycopg.connect(schema_dsn) as conn:
        seed_rows(conn, results)
        (results / ".work" / f"{source_hash(LABELS[0])}.png").write_bytes(b"not an image")
        ctx = NodeContext(tmp_path / "source", True, results, config, vision=backend)
        result = classify(conn, ctx)
        conn.commit()
    rows = _rows(schema_dsn)
    assert (result.classified, result.errored) == (len(LABELS) - 1, 1)
    assert dict(result.by_reason) == {WORKING_COPY_UNREADABLE: 1}
    bad = rows[source_hash(LABELS[0])]
    assert (bad["status"], bad["error"]) == ("error", WORKING_COPY_UNREADABLE)
    assert bad["format"] is None and bad["image_vec"] is None
    assert all(r["status"] == "classified" for h, r in rows.items() if h != source_hash(LABELS[0]))


def test_run_threads_the_vision_seam_and_reports_through_run_result(
    schema_dsn: str, tmp_path, vision_backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(vision_backend)
    config = make_config()
    monkeypatch.setenv("DB_DSN", schema_dsn)
    config = config.model_copy(update={"db": config.db.model_copy(update={"dsn": schema_dsn})})
    object.__setattr__(config.paths, "source_root", str(tmp_path / "source"))
    object.__setattr__(config.paths, "results_root", str(tmp_path / "results"))
    (tmp_path / "source").mkdir()
    with psycopg.connect(schema_dsn) as conn:
        seed_rows(conn, tmp_path / "results")
        conn.commit()
    result = run(config, dry_run=True, nodes=(Node("classify", classify),), vision=backend)
    assert list(result.counts) == ["classify"]
    assert result.classify.classified == len(LABELS)
    assert {r["status"] for r in _rows(schema_dsn).values()} == {"classified"}


def test_the_node_never_opens_the_source_root(
    schema_dsn: str, tmp_path, vision_backend
) -> None:  # P-1, CLS-002.D8
    backend = _backend(vision_backend)
    run_classify(schema_dsn, tmp_path, backend)
    source = tmp_path / "source"
    assert list(source.iterdir()) == []  # the folder was never written to
