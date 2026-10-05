"""Fetch the Hugging Face weights into the `hf` volume (R-MOD-2, RUN-001.D4).

Runs only in the compose `fetch` service, the one app-image container with internet.
At runtime the app sets HF_HUB_OFFLINE=1 and reads from the same volume.
Prefers safetensors; falls back to .bin only when a repo has no safetensors.
"""

import os
import sys
from pathlib import Path

import yaml
from huggingface_hub import HfApi, snapshot_download

CONFIG = Path(os.environ.get("CLASSIFIER_CONFIG", "/app/config.yaml"))
TEXT_FILES = ["*.json", "*.txt", "*.model"]


def patterns_for(repo_id: str) -> list[str]:
    files = HfApi().list_repo_files(repo_id)
    weights = ["*.safetensors"] if any(f.endswith(".safetensors") for f in files) else ["*.bin"]
    return TEXT_FILES + weights


def main() -> int:
    models = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["models"]
    for key in ("classifier", "nsfw"):
        repo_id = models[key]
        path = snapshot_download(repo_id=repo_id, allow_patterns=patterns_for(repo_id))
        size = sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())
        print(f"{key}: {repo_id} -> {path} ({size / 2**20:.0f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
