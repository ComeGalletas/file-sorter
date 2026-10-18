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
- the request has no `images` (an image request carries `image_digests`, below).

Whitespace and key order are free.

## Requests with images (TST-009.1, TST-009.D2)

A VLM call posts `images`, a list of base64 strings (1 to 8). A recording never holds them:

- **Key.** The same key, plus `image_digests` when the body carries images: the `image_digest` of each image (TST-008.D8: SHA-256 of the **decoded first frame**, i.e. `mode`, `size` and `tobytes()`, length-prefixed), in order. So the key follows the pixels the client actually sends: the same pixels in another encoding give the same key, and a re-encoded JPEG is keyed by its own decode. A body without images keys exactly as before.
- **Stored request.** The body as sent, with `images` replaced by `image_digests` (a list of 1 to 8 lowercase 64-hex digests, in order). Use `tests.recordings.replay.stored_request(body)`. A stored `images` field is a lint error. The key of the live body equals the key of its stored request.
- **Fields.** Every Ollama request, text-only or with images, may carry only `model`, `prompt`, `format`, `options`, `think`, `raw`, `keep_alive`, `stream` and `images` (`image_digests` when stored). Any other field is refused with fixed text at replay, at record (before anything is forwarded or written) and by the lint, so nothing unseen, such as a base64 value under a made-up key, can reach a recording (TST-009.1.5).
- **Prompt.** The `prompt` of an image request must pass TST-008.D9's text rule (`tests.recordings.vision.check_text_input`): only ASCII letters, digits, single spaces, commas and apostrophes (so no `.`), 1 to 256 characters, no leading or trailing space, at least one letter, and no word of 3 or more digits. Record mode and the replay refuse a prompt outside it, before anything is forwarded or written. Text-only recordings keep their old freedom. Or it is a rendering of a committed prompt (below).
- **Limits.** At most 8 images per request, 8 MiB per decoded image and 16 million pixels (checked before any pixel is decoded). An image that is not strict base64 of a decodable image, or is over a limit, is refused with fixed text.
- **Not provable.** The lint cannot show that the reply text, or the phrase in the prompt, is synthetic. The privacy review of each committed VLM recording covers it, so record only from synthetic pictures and invented prompts.
- **In a test.** `OllamaClient.generate_json` has no `images` argument yet (CLS-004.2 adds it). Until then, post the body through `httpx` as the tests in `tests/devtools/test_recordings.py` do.

### Prompts rendered from a committed `prompts/` file (TST-010.1)

`prompts/classify_v1.md` and `prompts/nsfw_level_v1.md` render to text far outside the D9 rule, and split a system text from a user text. So an image request may also carry `system` (keyed like `prompt`, only when present, so existing keys are unchanged), and its `prompt` and `system` are each **either** D9 text **or** a rendering of a committed prompt file. The recording stores the exact text sent (replay is exact) and, when a part is not D9 text, a `prompt_source`:

```
"prompt_source": {"name": "classify_v1", "sha256": "<hash of prompts/classify_v1.md>",
                  "system": {"slots": {"formats": "...", "topics": "..."}},
                  "prompt": {"alt": true, "slots": {"name": "..."}}}
```

- **Nothing to add in a test.** The client sends text only. `stored_request(body)` (and the record transport) finds the prompt by matching the text against each committed file and writes `prompt_source`. A body that carries one is verified the same way, so it can't be forged.
- **The check** (`tests/recordings/prompts.py`, one function for record, replay and the lint): the file must load, its LF-normalised SHA-256 must equal `sha256`, every slot value must pass its rule, and `Prompt.render` (system) or `render_user(alt=...)` (prompt) of the stored slots must equal the text exactly. A recording therefore holds only committed text plus checked slot values.
- **Slot rules, by slot name.** `formats` and `topics` take a `", "`-joined category list: names of `[a-z0-9]+(-[a-z0-9]+)*`, 1 to 40 characters each, 1 to 64 names, no repeats, nothing else (so DESIGN §4.3's default names pass). Every other slot, `name` included, takes TST-008.D9's text rule. The client must join the lists with `", "`.
- **Stale recordings.** Edit or rename a prompt file and the lint fails, naming the recording: `its prompt file changed since it was recorded; re-record it`, or `its prompt file is missing or invalid; re-record it`. Replay of such a recording fails the same way. Delete it and re-record in the `gpu` tier.
- **Refusals.** Text that is neither D9 text nor a committed rendering, a bad slot, a mismatched or malformed `prompt_source`, or a `prompt_source` on a text-only request is refused with fixed text (no prompt, slot or path) before anything is forwarded or written. Only image requests may carry one.
- **In a test of the checker.** The module reads `tests.recordings.prompts.PROMPTS_DIR` at call time; monkeypatch it to a temporary copy to test an edit or a rename.

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
