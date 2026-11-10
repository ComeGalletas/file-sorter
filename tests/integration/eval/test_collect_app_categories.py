"""CLS-007.4.3: `collect` end to end with the app database's categories (a fake app source).

The real ingest and sanitize nodes run in a throwaway migrated schema on one synthetic picture;
the VLM is a scripted client, the Falconsai gate a number. The names and the description are
synthetic coinages. Nothing here reads a fixture or the real app database.
"""

import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

from tests.db.db_support import require_db_dsn
from tests.integration.classify_support import make_image
from tests.integration.schema_support import migrated_schema

REPO = Path(__file__).resolve().parents[3]
for folder in (REPO / "eval", REPO / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import classify_eval as ev  # noqa: E402

from classifier.models.ollama import OllamaClient  # noqa: E402
from classifier.sanitize.rules import LOG_KEY_ENV  # noqa: E402

PLANT = "plantedwording_zq marker"
APP_FORMAT, APP_TOPIC = "Qorvexzh", "Vrellikon"
LABELS = "file,format,topic,adult,reference,subject,tags\nonly.png,{fmt},{topic},no,,,\n"
RULES = "exif: {mode: strip_all}\nrules: []\n"


class FakeBackend:
    nsfw_id = "fake-nsfw"

    def nsfw_scores(self, images):
        return np.array([0.1 for _ in images], dtype=np.float32)


def scripted(fmt: str, topic: str) -> tuple[OllamaClient, list[dict]]:
    """The format/topic reply first, then the level reply: the order the eval asks in."""
    seen: list[dict] = []
    queue = [
        {"observation": "synthetic cues", "format": fmt, "topic": topic},
        {"observation": "synthetic cues", "nsfw_level": "safe", "traces": False},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps(queue.pop(0))})

    return OllamaClient("http://ollama", transport=httpx.MockTransport(handler)), seen


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(LOG_KEY_ENV, "00112233445566778899aabbccddeeff")
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    real = ev.gate.load_config
    monkeypatch.setattr(
        ev.gate,
        "load_config",
        lambda source, results, dsn, rules_path=None: real(source, results, dsn, rules),
    )


@pytest.fixture
def prompts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The committed prompts plus a local classify prompt that uses the definition slots.

    The committed text leaves the slots out (CLS-007.D1), so only a replacement that uses them
    shows what the model is sent.
    """
    from classifier.models import vlm_classify as vlm_module

    monkeypatch.delenv("PROMPTS_LOCAL", raising=False)
    folder = tmp_path / "prompts"
    (folder / "local").mkdir(parents=True)
    for name in ev.PROMPT_NAMES:
        (folder / f"{name}.md").write_bytes((ev.PROMPTS_DIR / f"{name}.md").read_bytes())
    body = "Formats:\n{format_definitions}\nTopics:\n{topic_definitions}\nList: {formats}"
    (folder / "local" / "classify_v1.md").write_text(body, encoding="utf-8")
    real = vlm_module.load_effective_prompt
    monkeypatch.setattr(vlm_module, "load_effective_prompt", lambda n: real(n, folder))
    return folder


@pytest.fixture
def images(tmp_path: Path) -> Path:
    root = tmp_path / "images"
    root.mkdir()
    make_image("img-a").save(root / "only.png")
    return root


def seeded_names() -> tuple[str, str]:
    import psycopg

    with migrated_schema(require_db_dsn()) as schema, psycopg.connect(schema) as conn:
        pick = {}
        for axis in ("format", "topic"):
            row = conn.execute(
                "select name from categories where axis = %s order by id limit 1", (axis,)
            ).fetchone()
            pick[axis] = str(row[0])
    return pick["format"], pick["topic"]


def app_set(description: str | None) -> list[ev.AppCategory]:
    return [
        ev.AppCategory("format", APP_FORMAT, "Qz", "any", description, None),
        ev.AppCategory("topic", APP_TOPIC, "Vk", "any", description, None),
    ]


def run(images, tmp_path, prompts, fmt, topic, app, cache) -> tuple[ev.Collected, list[dict]]:
    labels = tmp_path / "labels.csv"
    labels.write_text(LABELS.format(fmt=fmt, topic=topic), encoding="utf-8")
    client, seen = scripted(fmt, topic)
    got = ev.collect(
        require_db_dsn(),
        images,
        labels,
        client,
        FakeBackend(),
        cache,
        prompts_dir=prompts,
        label_check=lambda _id: True,
        app_categories=app,
    )
    return got, seen


def test_app_descriptions_and_app_only_categories_reach_the_request_and_the_cache_key(
    tmp_path, images, prompts_dir
):
    seeded_fmt, seeded_topic = seeded_names()
    caches = [tmp_path / "seeded-cache", tmp_path / "app-cache", tmp_path / "other-cache"]

    plain, plain_seen = run(
        images, tmp_path, prompts_dir, seeded_fmt, seeded_topic, None, caches[0]
    )
    got, seen = run(images, tmp_path, prompts_dir, APP_FORMAT, APP_TOPIC, app_set(PLANT), caches[1])

    assert plain.descriptions == "seeded" and plain.skipped is None
    assert got.descriptions == "app database" and got.skipped == 0
    assert PLANT not in json.dumps(plain_seen) and APP_FORMAT not in json.dumps(plain_seen)
    request = json.dumps(seen[0])  # the first call is the format/topic one
    assert PLANT in request and APP_FORMAT in request and APP_TOPIC in request
    assert got.measures.format.hit == 1 and got.measures.topic.hit == 1
    assert PLANT not in "\n".join(ev.render(got, True))

    # A run that changes only the description writes another cache file, so a stale answer is
    # never reused across descriptions.
    run(images, tmp_path, prompts_dir, APP_FORMAT, APP_TOPIC, app_set(PLANT + " two"), caches[2])
    keys = [sorted(p.name for p in c.glob("*.json")) for c in caches]
    assert all(len(k) == 1 for k in keys) and len({k[0] for k in keys}) == 3
