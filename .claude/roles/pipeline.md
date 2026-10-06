# Pipeline engineer (Sonnet)

**Owns:** `classifier/graph/`, `classifier/naming/`, `classifier/fileops/`, `classifier/db/` (Alembic: one head, rebase and fix `down_revision` before merge), `classifier/cli/`, `classifier/sanitize/`.

**Responsibility:** the LangGraph nodes and their batch execution (R-PIPE), the ledger and its status checkpoint (DESIGN §5), sanitization (R-SAN), naming templates and tokens (R-NAME), the copy → results transaction and `watch` (R-FOP), and the CLI (§7).

**Watch out for:**
- The source is read-only. The only delete code is `fileops/delete.py`, and it is disabled by default (R-FOP-0).
- The `files.status` enum is the only checkpoint; nodes must be idempotent.
- Never log original filenames or EXIF values: use hashes (CLAUDE.md "Hard rules").
- Hand-tuned values in `config.yaml`: flag and ask (CLAUDE.md §1.7).

Start every task as in [README.md](README.md).
