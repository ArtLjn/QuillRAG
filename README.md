<p align="center">
  <img src="docs/banner.svg" alt="QuillRAG" width="100%"/>
</p>

<p align="center">
  <a href="README_zh.md">简体中文</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/ArtLjn/QuillRAG"><img alt="version" src="https://img.shields.io/badge/version-0.3.3-blue.svg"/></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg"/></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue.svg"/></a>
  <a href="https://fastapi.tiangolo.com"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg"/></a>
  <a href="https://qdrant.tech"><img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-1.11%2B-dc382d.svg"/></a>
</p>

# QuillRAG

**QuillRAG** is an independent Retrieval-Augmented Generation service. It packages document parsing, chunking, hybrid retrieval, reranking, metadata management, retrieval evaluation, and a small browser UI behind a FastAPI service that can be deployed next to any LLM application.

Inspired by [airQA / NSQA](https://github.com/ArtLjn/NSQA), it keeps the research-grade retrieval ideas while exposing them as a service you can run locally, in Docker, or behind another application.

## Highlights

- **Document parsing**: PDF parsing through MinerU cloud API when configured, with PyMuPDF / OCR fallback for offline use; Markdown and plain text are supported too.
- **Chunking strategies**: `structure_aware`, `markdown_structure`, `semantic`, and `fixed`, selected automatically by file type or passed explicitly in API calls.
- **Hybrid retrieval**: dense vector search + BM25 sparse search with RRF / MinMax score normalization, diversity penalty, and Jaccard deduplication.
- **Reranking is optional**: disabled by default; providers include `flashrank`, `jina`, `llm`, and local `BAAI/bge-reranker-v2-m3`.
- **Operational surface**: `/health`, request IDs, slow request warnings, JSON/text logs, SQLite metadata, Qdrant storage, and retrieval evaluation reports.
- **Built-in UI and auth**: `/ui/` supports ingest, retrieval, collections, documents, evaluation, and health pages. Auth can use `X-API-Key` for services and session cookies for the browser UI.

## Docker Deployment

The fastest deployment path is Docker Compose. It starts QuillRAG and a local Qdrant instance, persists Qdrant data and QuillRAG metadata, and uses `.env` for runtime configuration.

```bash
cp .env.example .env
# Edit .env at least:
#   EMBEDDING_API_KEY=...
# Optional:
#   MINERU_API_TOKEN=...
#   AUTH_ENABLED=true
#   AUTH_API_KEY=...
#   AUTH_PASSWORD_HASH=...
#   AUTH_SESSION_SECRET=...

bash deploy/docker-deploy.sh up
```

Open [http://127.0.0.1:8001/ui/](http://127.0.0.1:8001/ui/).

Common Docker commands:

```bash
bash deploy/docker-deploy.sh status
bash deploy/docker-deploy.sh logs
bash deploy/docker-deploy.sh health
bash deploy/docker-deploy.sh restart
bash deploy/docker-deploy.sh down
```

`reset` removes Docker volumes and deletes all local Qdrant / metadata data:

```bash
bash deploy/docker-deploy.sh reset
```

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# If you use local Docker Qdrant without Compose for the app:
# docker compose up -d qdrant
# set QDRANT_URL=http://localhost:6333

uvicorn app.main:app --reload --port 8001
```

## API Overview

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Component health for Qdrant, embedder, and reranker |
| `/parse` | POST | Parse and chunk a file or text without writing to storage |
| `/ingest` | POST | Parse, chunk, embed, write vectors to Qdrant, and write metadata to SQLite |
| `/retrieve` | POST | Retrieve with `vector`, `bm25`, or `hybrid` mode |
| `/rerank` | POST | Rerank candidate documents with the configured provider |
| `/collections` | GET/POST | List or create collections |
| `/collections/{name}` | DELETE | Delete a collection |
| `/collections/{name}/documents` | GET | List documents in a collection |
| `/collections/{name}/documents/{doc_id}` | DELETE | Delete one document |
| `/collections/{name}/documents:batch-delete` | POST | Delete multiple documents |
| `/collections/{name}/prune-orphans` | POST | Remove Qdrant points that no longer have metadata |
| `/evaluation/latest` | GET | Read the latest retrieval evaluation report |
| `/evaluation/run` | POST | Run retrieval evaluation against a JSONL golden set |
| `/ui/` | GET | Browser UI |
| `/docs` | GET | Swagger UI |

## Configuration

The full configuration lives in `.env.example` and is loaded by `app/core/config.py`.

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8001` | HTTP listen port |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint; Docker Compose overrides it to `http://qdrant:6333` |
| `QDRANT_API_KEY` | empty | Qdrant API key; leave empty for the bundled local Qdrant |
| `EMBEDDING_PROVIDER` | `google` | `google` or `openai` |
| `EMBEDDING_BASE_URL` | Google Gemini API | Embedding API base URL |
| `EMBEDDING_API_KEY` | empty | Required for online embedding providers |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model name |
| `EMBEDDING_DIM` | `3072` | Vector dimension used when creating collections |
| `MINERU_API_TOKEN` | empty | Enables MinerU cloud PDF parsing; empty uses PyMuPDF fallback |
| `RERANKER_ENABLED` | `false` | Set to `true` to enable reranking |
| `RERANKER_PROVIDER` | `local` in code, `flashrank` in `.env.example` | `flashrank`, `jina`, `llm`, or `local` when enabled |
| `HYDE_ENABLED_BY_DEFAULT` | `false` | Enables HyDE query rewriting by default |
| `DEFAULT_CHUNK_SIZE` | `500` | Default chunk size |
| `DEFAULT_CHUNK_OVERLAP` | `50` | Default chunk overlap |
| `DEFAULT_TOP_K` | `10` | Default retrieval result count |
| `METADATA_DB_PATH` | `data/rag_metadata.db` | SQLite metadata path |
| `LOG_FORMAT` | `text` | `text` or `json` |
| `AUTH_ENABLED` | `false` | Enable API/UI auth for public deployments |
| `AUTH_API_KEY` | empty | API key accepted through `X-API-Key` |
| `AUTH_USERNAME` | `admin` | Browser UI username |
| `AUTH_PASSWORD_HASH` | empty | bcrypt password hash for UI login |
| `AUTH_SESSION_SECRET` | empty | Cookie signing secret |

## Architecture

```text
HTTP -> AuthMiddleware -> RequestLoggingMiddleware
  -> /parse      -> parser/{MinerU, PyMuPDF, Markdown, Text} -> chunker -> cleaner
  -> /ingest     -> parse -> embed -> Qdrant + SQLite metadata + version history
  -> /retrieve   -> dense + sparse -> fusion -> diversity -> dedup
  -> /rerank     -> provider-pluggable reranker -> top-k
  -> /evaluation -> golden set runner -> JSON reports
```

See [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/deployment.md](docs/deployment.md), and [docs/evaluation.md](docs/evaluation.md) for deeper notes.

## Evaluation

Retrieval evaluation supports `recall@k`, `precision@k`, `MRR`, `NDCG@k`, and `hit_rate`.

```bash
python scripts/eval_retrieval.py \
  --dataset fixtures/evaluation/retrieval.example.jsonl \
  --report-dir data/evaluation/reports
```

Reports are available from `/evaluation/latest`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

Integration tests that require live Qdrant are marked with `integration`.

## License

[MIT](LICENSE) © 2026 [ArtLjn](https://github.com/ArtLjn)

## Acknowledgements

- [airQA / NSQA](https://github.com/ArtLjn/NSQA)
- [MinerU](https://mineru.net)
- [Qdrant](https://qdrant.tech)
- [BAAI](https://github.com/UKPLab)
- [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank)
