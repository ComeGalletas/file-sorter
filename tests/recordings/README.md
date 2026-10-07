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
