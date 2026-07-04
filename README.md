<p align="center">
  <img src="docs/banner.svg" alt="QuillRAG" width="720"/>
</p>

<p align="center">
  <a href="README_zh.md">简体中文</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/ArtLjn/QuillRAG"><img alt="tests" src="https://img.shields.io/badge/tests-167%2F167-brightgreen.svg"/></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg"/></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue.svg"/></a>
  <a href="https://fastapi.tiangolo.com"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg"/></a>
  <a href="https://qdrant.tech"><img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-1.11%2B-dc382d.svg"/></a>
</p>

# QuillRAG

**QuillRAG** is a standalone Retrieval-Augmented Generation service. Drop it next to your LLM application and get production-grade PDF parsing, hybrid retrieval, and Cross-Encoder reranking behind a clean HTTP API.

Inspired by [airQA / NSQA](https://github.com/ArtLjn/NSQA) — academic-grade retrieval patterns distilled into a deployable service.

## ✨ Highlights

- **PDF parsing done right** — MinerU cloud API (SOTA, online) with PyMuPDF heuristic fallback (offline). Tables, formulas, figures, two-column layouts, page headers/footers — all handled.
- **Hybrid retrieval** — Dense + Sparse (BM25) fusion with RRF or MinMax normalization + diversity penalty.
- **5-provider reranker** — `disabled` / `flashrank` (local ONNX, 18-120 MB) / `jina` (free 1M tokens/mo) / `llm` (any OpenAI-compatible) / `local` (BAAI bge-reranker-v2-m3).
- **Beyond text** — Tables serialize to `key=value` records (BM25 hits field queries). Formulas LaTeX → Unicode (`\alpha` → `α`) for lexical search.
- **Production-friendly** — Lazy-loaded models (idle/ok/failed health semantics), `request_id` tracing, slow-request warnings, JSON/text dual-format logging.
- **Auth out of the box** — `X-API-Key` for service-to-service, session cookie for browser UI.
- **Live UI** — TailwindCSS dashboard at `/ui/` for ingest / retrieve / browse chunks, zero frontend build step.

## 📦 API at a glance

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Health check (Qdrant / Embedder / Reranker status) — public |
| `/parse` | POST | Parse document → preview chunks (no write) |
| `/ingest` | POST | Parse + chunk + embed + write to Qdrant |
| `/retrieve` | POST | Hybrid (vector / bm25 / hybrid) retrieval |
| `/rerank` | POST | Cross-Encoder rerank of retrieved candidates |
| `/collections` | GET/POST/DELETE | Manage collections and documents |
| `/ui/` | GET | Web UI (login required when auth on) |
| `/docs` | GET | Swagger UI (auth required in production) |

## 🚀 Quick start

```bash
git clone https://github.com/ArtLjn/QuillRAG.git
cd QuillRAG
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in: QDRANT_URL/API_KEY, EMBEDDING_API_KEY, optional MINERU_API_TOKEN

uvicorn app.main:app --reload --port 8001
```

Open [http://127.0.0.1:8001/ui/](http://127.0.0.1:8001/ui/).

## 🔧 Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8001` | HTTP listen port |
| `QDRANT_URL` / `QDRANT_API_KEY` | — | Qdrant endpoint |
| `EMBEDDING_PROVIDER` | `google` | `google` / `openai` |
| `EMBEDDING_API_KEY` | — | Google gemini or OpenAI key |
| `EMBEDDING_DIM` | `3072` | gemini-embedding-001 default |
| `MINERU_API_TOKEN` | — | https://mineru.net free 100 pages/day |
| `RERANKER_PROVIDER` | `flashrank` | `disabled` / `flashrank` / `jina` / `llm` / `local` |
| `AUTH_ENABLED` | `false` | Enable auth (recommended for public deploy) |
| `AUTH_API_KEY` | — | Service-to-service Bearer token |

Full config in [`docs/deployment.md`](docs/deployment.md).

## 🏗 Architecture

```
HTTP → AuthMiddleware → RequestLoggingMiddleware
  → /parse  → parser/{MinerU,PyMuPDF,Markdown,Text} → chunker → cleaner
  → /ingest → parse → embed → Qdrant + SQLite metadata + version history
  → /retrieve → dense + sparse → RRF/MinMax fusion → diversity → dedup
  → /rerank → Cross-Encoder (provider-pluggable) → top-k
```

Modules borrowed from airQA:
- MinerU client (HTTP upload + poll + zip parse)
- BlockType constants (50+ types) and category mapping
- LaTeX normalization + Unicode symbol mapping
- Two-column reading-order restoration (x0 clustering)
- Spatial-distance semantic anchors for tables/formulas/figures
- `logic_idx` global reading order + prev/next neighbor IDs

See [`docs/architecture.md`](docs/architecture.md).

## 📊 Evaluation hooks

Built-in metrics at `app/evaluation/metrics.py`: `recall_at_k`, `precision_at_k`, `mrr`, `ndcg_at_k`. Plug in your golden set for thesis experiments.

## 📄 License

[MIT](LICENSE) © 2026 [ArtLjn](https://github.com/ArtLjn)

## 🙏 Acknowledgements

- [airQA / NSQA](https://github.com/ArtLjn/NSQA) — academic RAG patterns
- [MinerU](https://mineru.net) — SOTA PDF parsing
- [Qdrant](https://qdrant.tech) — vector database
- [BAAI](https://github.com/UKPLab) — bge embedding / reranker models
- [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank) — ONNX reranker
