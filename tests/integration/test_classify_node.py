"""CLS-004.4: the classify node on synthetic images with replayed model output (acceptance).

The scenario is `classify_support.run_classify`: five benign synthetic pictures (four stills and
one animated), four coined categories and the name hints in `HINTS`. SigLIP's and Falconsai's
answers replay from `tests/recordings/graph/` (TST-008.D3) and the VLM's from
`tests/recordings/models/` (CLS-004.2.6, the same scenario). Nothing here loads a model or
reaches Ollama.

The expected rows are computed independently of the node: the same recordings answer
`vlm_classify` for each working copy opened as the node opens it, then CLS-004.3's `decide`
turns the answer into the branch, format, topic and review flags. The Falconsai score comes from
the replay (flat pictures never score as adult on the real gate, so the cross-check stays off in
the committed config). Replay is exact: a request the node no longer sends the same way misses
its recording and fails.
"""

import numpy as np
import psycopg
import pytest

from classifier.config import load_config
from classifier.graph.classify import (
    WORKING_COPY_UNREADABLE,
    ClassifyResult,
    _load_rules,
    classify,
    first_frame_rgb,
    open_working_frames,
)
from classifier.graph.nodes import Node, NodeContext
from classifier.graph.run import run
from classifier.models.classify_rules import decide
from classifier.models.ollama import OllamaClient
from classifier.models.vlm_classify import vlm_classify
from tests.integration.classify_support import (
    FORMATS,
    HINTS,
    SCENARIO_LABELS,
    TOPICS,
    make_config,
    run_classify,
    seed_scenario,
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
    models = load_config().models
    return vision_backend("graph", models.classifier, models.nsfw)


def _rows(dsn: str) -> dict[str, dict[str, object]]:
    with psycopg.connect(dsn) as conn:
        cursor = conn.execute(
            "select source_hash, status, branch, nsfw_score, nsfw_level, format, topic,"
            " format_scores, topic_scores, needs_review, review_reason, image_vec::text, error"
            " from files"
        )
        names = [c.name for c in cursor.description]
        return {r[0]: dict(zip(names, r, strict=True)) for r in cursor.fetchall()}


def _expected(dsn, backend, results, config, ollama_transport, label: str):
    """The row the node must write for `label`, from the client, `decide` and the same replay."""
    with psycopg.connect(dsn) as conn:
        rules = _load_rules(conn)
    digest = source_hash(label)
    frames = open_working_frames(results / ".work", digest, "png")
    first = first_frame_rgb(frames)
    nsfw = float(backend.nsfw_scores([first])[0])
    with OllamaClient("http://ollama:11434", transport=ollama_transport("models")) as client:
        answer = vlm_classify(
            client,
            config.models.vlm_safe,
            frames,
            hint=HINTS.get(label),
            formats=list(FORMATS),
            topics=list(TOPICS),
        )
    return answer, nsfw, decide(answer, rules, nsfw, config.nsfw)


def _check_rows(dsn, backend, results, config, ollama_transport, rows) -> None:
    for label in SCENARIO_LABELS:
        answer, nsfw, choice = _expected(dsn, backend, results, config, ollama_transport, label)
        row = rows[source_hash(label)]
        assert row["status"] == "classified"  # a dry run stops here
        assert (row["branch"], row["format"], row["topic"]) == (
            choice.branch,
            choice.format,
            choice.topic,
        )
        assert row["nsfw_level"] == answer.level.name
        assert row["nsfw_score"] == pytest.approx(nsfw, abs=1e-6)
        assert (row["needs_review"], row["review_reason"]) == (
            choice.needs_review,
            choice.review_reason,
        )
        assert row["format_scores"] is None and row["topic_scores"] is None  # CLS-004.D7
        assert row["error"] is None


def test_every_sanitized_row_is_classified_as_decide_says(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport
) -> None:
    backend = _backend(vision_backend)
    result, config = run_classify(schema_dsn, tmp_path, backend, ollama_transport("models"))
    rows = _rows(schema_dsn)
    assert len(rows) == len(SCENARIO_LABELS)
    _check_rows(schema_dsn, backend, tmp_path / "results", config, ollama_transport, rows)
    unsorted = sum(r["format"] == "unsorted" for r in rows.values())
    no_topic = sum(r["topic"] is None for r in rows.values())
    adult = sum(r["branch"] == "nsfw" for r in rows.values())
    assert result == ClassifyResult(
        classified=len(SCENARIO_LABELS), unsorted=unsorted, no_topic=no_topic, adult=adult
    )
    assert all(
        r["nsfw_level"] in ("safe", "suggestive", "nudity", "explicit") for r in rows.values()
    )


def test_the_stored_vector_is_the_recorded_embedding(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport
) -> None:  # CLS-002.D10
    backend = _backend(vision_backend)
    run_classify(schema_dsn, tmp_path, backend, ollama_transport("models"))
    rows = _rows(schema_dsn)
    for label in SCENARIO_LABELS:
        digest = source_hash(label)
        frames = open_working_frames(tmp_path / "results" / ".work", digest, "png")
        image = first_frame_rgb(frames)
        stored = np.array(rows[digest]["image_vec"].strip("[]").split(","), dtype=np.float32)
        assert stored.shape == (1152,)
        np.testing.assert_allclose(stored, backend.embed_images([image])[0], atol=1e-6)


def test_the_gate_score_never_decides_the_branch(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport
) -> None:  # CLS-004.D5: Falconsai is a cross-check, and the scenario config has it off
    plain = _backend(vision_backend)
    run_classify(schema_dsn, tmp_path / "plain", plain, ollama_transport("models"))
    baseline = _rows(schema_dsn)
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("delete from files")
        conn.commit()
    gate = NumericGate(plain, 0.99)
    run_classify(schema_dsn, tmp_path / "gated", gate, ollama_transport("models"))
    gated = _rows(schema_dsn)
    for digest, row in gated.items():
        assert row["nsfw_score"] == pytest.approx(0.99, abs=1e-6)
        for column in ("branch", "format", "topic", "nsfw_level", "needs_review", "review_reason"):
            assert row[column] == baseline[digest][column]


def test_a_rerun_changes_nothing_and_asks_the_models_for_nothing(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport
) -> None:
    backend = _backend(vision_backend)
    run_classify(schema_dsn, tmp_path, backend, ollama_transport("models"))
    before = _rows(schema_dsn)
    with psycopg.connect(schema_dsn) as conn:
        ctx = NodeContext(tmp_path / "source", True, tmp_path / "results", make_config())
        # No vision and no transport on the context: a re-run must not build either client.
        assert classify(conn, ctx) == ClassifyResult()
        conn.commit()
    assert _rows(schema_dsn) == before


def test_one_unreadable_copy_errors_alone_and_the_rest_are_classified(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport
) -> None:  # CLS-002.D7
    backend = _backend(vision_backend)
    results = tmp_path / "results"
    config = make_config()
    (tmp_path / "source").mkdir()
    bad_label = SCENARIO_LABELS[0]
    with psycopg.connect(schema_dsn) as conn:
        seed_scenario(conn, results)
        (results / ".work" / f"{source_hash(bad_label)}.png").write_bytes(b"not an image")
        ctx = NodeContext(
            tmp_path / "source",
            True,
            results,
            config,
            ollama_transport=ollama_transport("models"),
            vision=backend,
        )
        result = classify(conn, ctx)
        conn.commit()
    rows = _rows(schema_dsn)
    bad = rows[source_hash(bad_label)]
    assert (result.classified, result.errored) == (len(SCENARIO_LABELS) - 1, 1)
    assert dict(result.by_reason) == {WORKING_COPY_UNREADABLE: 1}
    assert (bad["status"], bad["error"]) == ("error", WORKING_COPY_UNREADABLE)
    assert bad["format"] is None and bad["nsfw_level"] is None and bad["image_vec"] is None
    others = (r for h, r in rows.items() if h != source_hash(bad_label))
    assert all(r["status"] == "classified" for r in others)


def test_run_threads_both_seams_and_reports_through_run_result(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _backend(vision_backend)
    config = make_config()
    monkeypatch.setenv("DB_DSN", schema_dsn)
    config = config.model_copy(update={"db": config.db.model_copy(update={"dsn": schema_dsn})})
    object.__setattr__(config.paths, "source_root", str(tmp_path / "source"))
    object.__setattr__(config.paths, "results_root", str(tmp_path / "results"))
    (tmp_path / "source").mkdir()
    with psycopg.connect(schema_dsn) as conn:
        seed_scenario(conn, tmp_path / "results")
        conn.commit()
    result = run(
        config,
        dry_run=True,
        nodes=(Node("classify", classify),),
        vision=backend,
        ollama_transport=ollama_transport("models"),
    )
    assert list(result.counts) == ["classify"]
    assert result.classify.classified == len(SCENARIO_LABELS)
    assert {r["status"] for r in _rows(schema_dsn).values()} == {"classified"}


def test_the_node_never_opens_the_source_root(
    schema_dsn: str, tmp_path, vision_backend, ollama_transport
) -> None:  # P-1, CLS-002.D8
    run_classify(schema_dsn, tmp_path, _backend(vision_backend), ollama_transport("models"))
    source = tmp_path / "source"
    assert list(source.iterdir()) == []  # the folder was never written to
