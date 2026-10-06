# API/UI engineer (Sonnet)

**Owns:** `classifier/api/`, `classifier/ui/` (and `report.py` inside `api/`).

**Responsibility:**
- The FastAPI status, files and events endpoints (R-API-1, R-API-2).
- The write actions in M8 (R-API-3).
- The htmx or Alpine dashboard and review queue, with no build step (R-API-5).
- The HTML report (R-API-7).

**Watch out for:**
- **The app container is on an internal-only network** (RUN-001.D5). Exposing the UI on `127.0.0.1:8000` needs the localhost-only proxy planned for M4; never add `app` to the `egress` network.
- Every write goes through the same graph nodes as the CLI (R-API-4). There is no deletion in the UI (R-API-8).
- Adult thumbnails are blurred by default. Thumbnails come from `.work/thumbs/`, never from originals.

Start every task as in [README.md](README.md).
