"""CLS-004.4.5: the classify scenario shared by the acceptance test and the recorders.

The integration test replays the recordings under `tests/recordings/` (SigLIP's under `graph/`,
the VLM's under `models/`); the gpu recorders run this same scenario with the real models, so a
replay holds exactly the requests the node makes. ML's CLS-004.2.6 imports `FORMATS`, `TOPICS`,
`HINTS`, `make_image`, `make_animated` and `seed_scenario` from here, so there is one definition.
Everything is synthetic: flat and generated pictures built in code, hashes of made-up labels,
artificial category names and name hints. No fixture, no real name, no adult content.
"""

import base64
import hashlib
import io
import json
from pathlib import Path

import httpx
import psycopg
import yaml
from PIL import Image

from classifier.config import Config
from classifier.graph.classify import ClassifyResult, classify
from classifier.graph.nodes import NodeContext

REPO = Path(__file__).resolve().parents[2]
SIZE = 48
LABELS = ("img-a", "img-b", "img-c", "img-d")  # the four stills (gate 3's scenario uses these)
ANIMATED = "img-e"  # three frames: img-a, img-b, img-c, in that order (an animated PNG)
SCENARIO_LABELS = (*LABELS, ANIMATED)
# What the node passes the client, in `categories` id order (CLS-004.4.5.2).
FORMATS = ("qorvex", "zhyndel")
TOPICS = ("vrelk", "xandoz")
# `files.original_sanitized` per image, as stored; a missing label has no name.
HINTS = {
    "img-a": "xandoz notes",
    "img-c": "qorvex sketch, draft 2",
    ANIMATED: "zhyndel loop",
}


def source_hash(label: str) -> str:
    return hashlib.sha256(f"classify-scenario-{label}".encode()).hexdigest()


def make_image(label: str) -> Image.Image:
    """Four benign synthetic pictures: two flat colours, a gradient and a checkerboard."""
    image = Image.new("RGB", (SIZE, SIZE))
    pixels = image.load()
    for x in range(SIZE):
        for y in range(SIZE):
            if label == "img-a":
                pixels[x, y] = (200, 30, 30)
            elif label == "img-b":
                pixels[x, y] = (30, 30, 200)
            elif label == "img-c":
                pixels[x, y] = (x * 255 // (SIZE - 1), y * 255 // (SIZE - 1), 90)
            else:
                pixels[x, y] = (255, 255, 255) if (x // 8 + y // 8) % 2 else (0, 0, 0)
    return image


def make_animated() -> bytes:
    """The animated picture as animated-PNG bytes: lossless, so frame digests are stable."""
    frames = [make_image(label) for label in ("img-a", "img-b", "img-c")]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="PNG", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def make_config() -> Config:
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    return Config.model_validate(data)


def seed_categories(conn: psycopg.Connection) -> None:
    """Replace the seeded categories with the scenario's four, in `FORMATS`, `TOPICS` order."""
    conn.execute("delete from categories")
    for axis, names in (("format", FORMATS), ("topic", TOPICS)):
        for name in names:
            conn.execute(
                "insert into categories (axis, name, folder) values (%s, %s, %s)",
                (axis, name, f"{name}-{axis}"),
            )


def seed_rows(
    conn: psycopg.Connection, results: Path, labels: tuple[str, ...] = SCENARIO_LABELS
) -> None:
    """`sanitized` rows with a working copy each; the source path is a placeholder."""
    (results / ".work").mkdir(parents=True, exist_ok=True)
    for label in labels:
        digest = source_hash(label)
        copy = results / ".work" / f"{digest}.png"
        if label == ANIMATED:
            copy.write_bytes(make_animated())
        else:
            make_image(label).save(copy)
        conn.execute(
            "insert into files (source_hash, short_hash, source_path, source_mtime, ext, status,"
            " original_sanitized) values (%s, %s, '/source/placeholder.png', now(), 'png',"
            " 'sanitized', %s)",
            (digest, digest[:8], HINTS.get(label)),
        )


def seed_scenario(conn: psycopg.Connection, results: Path) -> None:
    """The categories and the five rows, in one call."""
    seed_categories(conn)
    seed_rows(conn, results)


def run_classify(
    dsn: str, tmp_path: Path, vision: object, ollama_transport: httpx.BaseTransport | None = None
) -> tuple[ClassifyResult, Config]:
    """Seed the scenario, run the node once and commit.

    `ollama_transport` is the replay transport in the integration tier; None reaches the real
    service, which only the gpu recorders do.
    """
    source, results = tmp_path / "source", tmp_path / "results"
    source.mkdir(exist_ok=True)
    config = make_config()
    with psycopg.connect(dsn) as conn:
        seed_scenario(conn, results)
        ctx = NodeContext(
            source,
            True,
            results,
            config,
            ollama_transport=ollama_transport,
            vision=vision,  # type: ignore[arg-type]
        )
        result = classify(conn, ctx)
        conn.commit()
    return result, config


class ScriptedVlm:
    """A scripted Ollama for the classify node's two calls (CLS-004.4); no real model.

    The level call rates a picture with a red first pixel above 128 as `nudity`, else `safe`
    (the same made-up gate the fake vision uses). The classify call answers `unsorted` when
    `unsorted` is set, else the first format and topic the request offers.
    """

    def __init__(self) -> None:
        self.unsorted = False
        self.requests = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        body = json.loads(request.content)
        picture = Image.open(io.BytesIO(base64.b64decode(body["images"][0]))).convert("RGB")
        properties = body["format"]["properties"]
        if "nsfw_level" in properties:
            level = "nudity" if picture.getpixel((0, 0))[0] > 128 else "safe"
            answer = {"observation": "synthetic cues", "nsfw_level": level}
        else:
            fmt = "unsorted" if self.unsorted else properties["format"]["enum"][0]
            topic = "none" if self.unsorted else properties["topic"]["enum"][0]
            answer = {"observation": "synthetic cues", "format": fmt, "topic": topic}
        return httpx.Response(200, json={"response": json.dumps(answer)})
