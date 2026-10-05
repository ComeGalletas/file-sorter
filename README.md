# file-sorter

A local bot that sorts an image folder. For every image it:

1. strips sensitive metadata and redacts sensitive values from the filename;
2. classifies the image into a **format** (screenshot, game screenshot, meme, photo, artwork, document) and an optional **topic** (videogames, anime, …);
3. names the file from what is in it, plus a resolved reference (a game, a character, a product) where it can find one;
4. copies the result into `<Topic>/<Format>/` in a separate results folder.

Adult content is filed in the same tree under `Adult/`. Everything runs on one machine in Docker. The source folder is mounted **read-only** and is never modified.

Status: **pre-alpha, bootstrap.** Nothing sorts yet; milestones are listed in [DESIGN.md](DESIGN.md) §11.

## Documents

| File | What it is |
| --- | --- |
| [DESIGN.md](DESIGN.md) | The normative spec: requirements (`R-…`), data model, config, milestones and gates |
| [CLAUDE.md](CLAUDE.md) | Working rules for the Claude Code agents that build this, including the process standard |
| [docs/journals/INDEX.md](docs/journals/INDEX.md) | Every work item (`CLS-001`, …) with its journal and status |
| [docs/PLAN.md](docs/PLAN.md) | The original plan and its rationale |

## Running it

Requires Windows 11 (or Linux) with an NVIDIA GPU and Docker Desktop with GPU support, git, Git Bash and `make`. See DESIGN.md §9a.

```bash
make init      # creates .env and sanitize.yaml from the examples; set SOURCE_ROOT and RESULTS_ROOT in .env
make up        # starts db, ollama, searxng and the app
make models    # pulls the models (about 11 GB)
make test      # unit + db + integration tests in Docker
```

The `torch` dependency is installed by the Dockerfile from PyTorch's CUDA index, not from `pyproject.toml`.
