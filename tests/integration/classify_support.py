"""CLS-002.2.4: the classify scenario shared by the acceptance test and the gpu recorder.

The integration test replays `tests/recordings/graph/`; the gpu recorder
(`tests/gpu/graph/test_record_classify.py`) runs this same scenario with the real models under
`--record-vision`, so the replay holds exactly the requests the node makes. Everything here is
synthetic: flat and generated pictures built in code, hashes of made-up labels, and the DESIGN
§4.3 prompts the migration seeds. No fixture, no name, no adult content.
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
LABELS = ("img-a", "img-b", "img-c", "img-d")  # internal labels of the synthetic pictures
# Test-only thresholds, so the scenario is the same wherever it runs. They are not tuned
# values (CLS-003 owns those) and never reach config.yaml.
TEST_MIN_SCORE = 0.0001  # flat pictures score tiny sigmoids; margin 0 lets a winner show


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


def make_config() -> Config:
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    for axis in ("format", "topic"):
        data["classify"][axis]["default_min_score"] = TEST_MIN_SCORE
        data["classify"][axis]["margin"] = 0.0
    return Config.model_validate(data)


def seed_rows(conn: psycopg.Connection, results: Path, labels: tuple[str, ...] = LABELS) -> None:
    """`sanitized` rows with a working copy each; the source path is a placeholder."""
    (results / ".work").mkdir(parents=True, exist_ok=True)
    for label in labels:
        digest = source_hash(label)
        make_image(label).save(results / ".work" / f"{digest}.png")
        conn.execute(
            "insert into files (source_hash, short_hash, source_path, source_mtime, ext, status,"
            " original_sanitized) values (%s, %s, '/source/placeholder.png', now(), 'png',"
            " 'sanitized', 'synthetic-stem')",
            (digest, digest[:8]),
        )


def run_classify(dsn: str, tmp_path: Path, vision: object) -> tuple[ClassifyResult, Config]:
    """Seed the rows, run the node once on `vision` and commit."""
    source, results = tmp_path / "source", tmp_path / "results"
    source.mkdir(exist_ok=True)
    config = make_config()
    with psycopg.connect(dsn) as conn:
        seed_rows(conn, results)
        ctx = NodeContext(source, True, results, config, vision=vision)  # type: ignore[arg-type]
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
