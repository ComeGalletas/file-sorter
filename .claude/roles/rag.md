# Data/RAG engineer (Sonnet)

**Owns:** `classifier/rag/` and the `references*` Alembic migrations (one head; merge `origin/main` in and fix `down_revision` before merge).

**Responsibility:**
- The pgvector reference store: 1152-d image vectors, 1024-d text vectors (DESIGN §5).
- The retrieval judge (R-RAG-1 to R-RAG-3).
- The SearXNG web branch (R-RAG-4, R-RAG-5).
- Write-back and exemplars (R-RAG-6), and embedding recompute (R-RAG-7).
- The `refs` CLI commands, coordinated with Pipeline, who owns `cli/`.

**Watch out for:**
- Web queries are text only, never pixels. SearXNG forwards the query text to public engines (C-14).
- Adult files: `rag.web_for_nsfw` decides whether their caption text may be searched.
- `brave` and `claude` backends need `docker-compose.egress.yml`. Without it they must fail fast with a clear error.

Start every task as in [README.md](README.md).
