# Recorded Ollama responses (TST-005.1)

Outside the `gpu` tier, no test reaches Ollama (CLAUDE.md §3). Model calls replay the recordings in this folder instead. QA owns the format and the fixture. The worker whose task makes a recording commits it (TST-005.D1), made from **synthetic strings only** (SAN-001.D10): never a fixture name, a `sanitize.yaml` value or anything about the human's images.

## Using it in a test

```python
from classifier.models.ollama import OllamaClient


def test_something(ollama_transport):
    client = OllamaClient("http://ollama:11434", transport=ollama_transport("models"))
    ...
```

`ollama_transport(package)` is a fixture in `tests/conftest.py`, and it reads `tests/recordings/<package>/`:

- **Outside `gpu`** it always replays. A missing recording raises `RecordingError`. The message names the key, the package and the test, and nothing else. `RecordingError` is a `BaseException`, so neither `OllamaClient` nor a fail-closed `except Exception` can swallow it. If the code under test catches it anyway, the fixture fails the test at teardown.
- **In `gpu`** it is the real transport. With `--record-ollama` it records.

Only `POST /api/generate` is served. The host check in `OllamaClient` still runs, and the replay never opens a socket.

## Format (TST-005.D3, D5)

One file per request, `tests/recordings/<package>/<key>.json`:

```json
{"request": {"model": "...", "prompt": "...", "format": {}, "options": {}, "keep_alive": 0, "stream": false},
 "response": {"model": "...", "response": "{...}", "done": true}}
```

- **`key`** is the SHA-256 of the canonical request, in hex: `json.dumps({model, prompt, format, options, think?, raw?}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, encoded as UTF-8.
  - `think` and `raw` are part of the key only when the body carries them.
  - `keep_alive` and `stream` are never part of it.
  - Use `tests.recordings.replay.recording_key(body)`.
- **`request`** is the body as sent.
- **`response`** is Ollama's reply. Record mode leaves out `context`, the prompt's token ids.

`tests/devtools/test_recordings.py` checks every committed file:

- it sits directly in a `<package>/` folder;
- it holds exactly `request` and `response`;
- `response.response` is a string;
- its name is its request's key;
- the request has no `images`.

Whitespace and key order are free.

## Recording

Record in the `gpu` tier only, against the real `ollama` service (temperature 0 and a fixed seed in the prompt's front matter):

```bash
docker compose -p <project> --profile test run --rm test pytest -m gpu --record-ollama tests/gpu/<package>/<test>.py
```

- The `test` container mounts the checkout, so new files land in your worktree. Review them, then commit them with your task.
- `--record-ollama` is refused if the selection holds any test outside `gpu`.
- A recording that already exists with the same answer is left as it is.
- A different answer fails, naming the key. If the model or prompt changed on purpose, delete the file and record again.

# Recorded vision responses (TST-008.1)

The same rule holds for SigLIP and the NSFW gate: outside `gpu`, nothing loads a model. A test gets a `VisionBackend` (`classifier/models/vision.py`, MOD-002.D1) that replays these files. Recordings are made from **synthetic images and synthetic prompt strings only**.

## Using it in a test

```python
def test_something(vision_backend):
    backend = vision_backend("models", "synthetic/classifier-id", "synthetic/nsfw-id")
    ...
```

- **Outside `gpu`** it is a `ReplayVisionBackend`. A miss raises `RecordingError` (a `BaseException`) naming the package, the key, the kind and the test, and nothing else. A miss the code under test swallowed still fails the test at teardown.
- **In `gpu`** pass the real backend (the ML desk's session-scoped fixture) as `upstream=`. It comes back as it is, or, with `--record-vision`, wrapped by the recorder.

## Format (TST-008.D3, D7)

One file per request, `tests/recordings/<package>/<key>.json`:

```json
{"request": {"model": "...", "kind": "text", "input": "a photo of a cat"},
 "response": {"shape": [1152], "dtype": "float32", "data": "<base64 little-endian>"}}
```

- **`key`** is the SHA-256 of `json.dumps({model, kind, input}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` in UTF-8. Use `tests.recordings.vision.vision_key`.
- **`kind`** and **`input`**:

  | kind | input | shape |
  | --- | --- | --- |
  | `image` | `image_digest(image)`: SHA-256 of the decoded first frame (`mode`, `size`, `tobytes()`, length-prefixed). Never a path or a name. | `[dim]` |
  | `text` | the prompt string | `[dim]` |
  | `nsfw` | `image_digest(image)` | `[]` |
  | `param` | `logit_scale` or `logit_bias` | `[]` |

- **`model`** is `classifier_id` for `image`, `text` and `param`, and `nsfw_id` for `nsfw`.
- Arrays are float32, little-endian, base64, so the replay is exact. NaN and infinity are refused.

`tests/devtools/test_vision_recordings.py` lints every committed file (and `test_recordings.py` runs the same walk): a plain `<package>/` folder, no links, exactly `request` and `response`, exactly `model`, `kind`, `input`, the name is the key, a 64-hex input for `image` and `nsfw`, a `model` that is one of `models.classifier` or `models.nsfw` in the committed `config.yaml` (TST-008.D9; a test registers a synthetic id with the `extra_vision_models` fixture, for its own run, and only as `synthetic/<name>` with `<name>` of 1 to 40 characters from `a-z`, `0-9` and `-`), a text of at most 256 characters made only of ASCII letters, digits, single spaces, commas and apostrophes (no `.`, and none of `( ) - _ / \ ~ :`), with no leading or trailing space, at least one letter, and no word of 3 or more digits, strict base64 of the right length, at most 4096 floats, rank at most 2.

## Recording

Record in the `gpu` tier only, with the real models:

```bash
docker compose -p <project> --profile test run --rm test pytest -m gpu --record-vision tests/gpu/<package>/<test>.py
```

- `--record-vision` is refused if the selection holds any test outside `gpu`.
- An existing recording is kept when the new answer is within `atol=1e-3` (fp16 runs differ in the last bits). A bigger difference fails naming the key: delete the file to re-record on purpose.
- The recorder refuses an input the lint would refuse, so a model id or text outside those shapes never reaches disk.
