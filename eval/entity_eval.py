"""Eval for the entity prompt (MOD-001.2.4, MOD-001.D3), on synthetic names only.

Run in the `test` container, which reaches the compose `ollama` service:

    docker compose --profile test run --rm test python eval/entity_eval.py

It builds `--n` filename-shaped strings from the fictional lists in
`eval/data/entity_synthetic.yaml` with a pinned seed, runs `detect_entities` on each and on
every no-entity string, and prints percentages only:

- recall: the share of seeded entities whose every letter is covered by a returned span,
  i.e. nothing of the name would survive redaction (gate 2's residual criterion);
- exact: the share of seeded entities returned as one span with the right label;
- false redactions: the share of no-entity strings with any span returned, and the share
  of returned spans on the seeded strings that touch no seeded entity.
"""

import argparse
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from classifier.config import load_config
from classifier.models.ollama import OllamaClient, OllamaError
from classifier.models.text_llm import ENTITY_LABELS, Entity, detect_entities, entity_prompt

DATA = Path(__file__).resolve().parent / "data" / "entity_synthetic.yaml"
SEED = 20311
LABEL_OF = {"person": "PERSON", "person2": "PERSON", "org": "ORG", "place": "LOCATION"}


@dataclass(frozen=True)
class Seeded:
    value: str
    label: str
    start: int


@dataclass(frozen=True)
class Case:
    text: str
    seeded: tuple[Seeded, ...]


def _join(words: list[str], sep: str) -> str:
    return sep.join(words) if sep else "".join(w[:1].upper() + w[1:] for w in words)


def build_cases(data: dict, n: int, seed: int = SEED) -> list[Case]:
    """`n` seeded strings, the same for the same data, `n` and seed."""
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        pattern = data["patterns"][i % len(data["patterns"])]
        sep = rng.choice(data["separators"])
        values = {
            "person": _join(
                [rng.choice(data["people"]["first"]), rng.choice(data["people"]["last"])], sep
            ),
            "person2": rng.choice(data["people"]["first"]),
            "org": _join(rng.choice(data["orgs"]).split(), sep),
            "place": _join(rng.choice(data["places"]).split(), sep),
            "date": f"{rng.randint(2029, 2032)}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}",
            "year": str(rng.randint(2029, 2032)),
            "n": f"{rng.randint(1, 9999):04d}",
        }
        text, seeded, rest = "", [], pattern
        while "{" in rest:
            head, _, tail = rest.partition("{")
            key, _, rest = tail.partition("}")
            text += head
            if key in LABEL_OF:
                seeded.append(Seeded(values[key], LABEL_OF[key], len(text)))
            text += values[key]
        cases.append(Case(text + rest, tuple(seeded)))
    return cases


def _covered(text: str, entities: list[Entity]) -> list[bool]:
    mask = [False] * len(text)
    for e in entities:
        start = text.find(e.text)
        while start != -1:
            for i in range(start, start + len(e.text)):
                mask[i] = True
            start = text.find(e.text, start + 1)
    return mask


def score(cases: list[Case], found: list[list[Entity]]) -> dict[str, float]:
    total = recalled = exact = spans = spurious = 0
    for case, entities in zip(cases, found, strict=True):
        mask = _covered(case.text, entities)
        seeded_chars = set()
        for s in case.seeded:
            total += 1
            idx = range(s.start, s.start + len(s.value))
            seeded_chars.update(idx)
            if all(mask[i] for i in idx if case.text[i].isalpha()):
                recalled += 1
            if Entity(s.value, s.label) in entities:
                exact += 1
        for e in entities:
            spans += 1
            start = case.text.find(e.text)
            if not seeded_chars.intersection(range(start, start + len(e.text))):
                spurious += 1
    return {
        "recall": 100 * recalled / total,
        "exact": 100 * exact / total,
        "spurious_spans": 100 * spurious / spans if spans else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="the same prompt through Ollama's chat template, thinking on (MOD-001.D5's "
        "alternative), with no answer cap; for the record only",
    )
    parser.add_argument("--no-entity", type=int, default=None, help="use only the first N")
    args = parser.parse_args(argv)

    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    cases = build_cases(data, args.n, args.seed)
    plain = data["no_entity"][: args.no_entity]
    model = load_config().models.text_llm
    prompt = entity_prompt()
    path = "raw"
    if args.thinking:
        prompt = prompt.model_copy(update={"raw": False, "wrap": None, "num_predict": None})
        path = "thinking"
    errors = 0
    with OllamaClient.from_env() as client:

        def run(text: str) -> list[Entity]:
            nonlocal errors
            try:
                return detect_entities(
                    text, ENTITY_LABELS, client=client, model=model, prompt=prompt
                )
            except OllamaError:
                errors += 1  # fails closed in the app; a miss here
                return []

        started = time.monotonic()
        found = [run(c.text) for c in cases]
        flagged = sum(1 for text in plain if run(text))
        per_call = (time.monotonic() - started) / (len(cases) + len(plain))
    result = score(cases, found)
    result["false_redaction_no_entity"] = 100 * flagged / len(plain)
    result["errors"] = 100 * errors / (len(cases) + len(plain))
    print(
        f"prompt {prompt.version} ({path}) · model {model} · seed {args.seed} · n {args.n}"
        f" + {len(plain)} plain · {per_call:.1f} s a call"
    )
    for key, value in result.items():
        print(f"{key}: {value:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
