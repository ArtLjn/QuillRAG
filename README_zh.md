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

**QuillRAG** 是一个可独立部署的检索增强生成（RAG）服务，把文档解析、分块、混合检索、重排、元数据管理、检索评测和浏览器 UI 封装在 FastAPI 服务里，可以作为主系统 LLM 应用旁边的一层检索能力。

项目借鉴 [airQA / NSQA](https://github.com/ArtLjn/NSQA) 的学术级检索模式，并把它们整理成可本地运行、Docker 部署、HTTP 调用的服务形态。

## 核心能力

- **文档解析**：配置 MinerU token 后使用 MinerU 云端 PDF 解析；未配置时走 PyMuPDF / OCR 兜底；同时支持 Markdown 和纯文本。
- **多种分块策略**：支持 `structure_aware`、`markdown_structure`、`semantic`、`fixed`，可自动按文件类型选择，也可在 API 中显式指定。
- **混合检索**：Dense 向量检索 + BM25 稀疏检索，支持 RRF / MinMax 归一化、同文档多样性衰减和 Jaccard 去重。
- **重排可选**：默认关闭；开启后可选 `flashrank`、`jina`、`llm`、本地 `BAAI/bge-reranker-v2-m3`。
- **生产运维面**：提供 `/health`、request_id、慢请求告警、JSON/text 日志、SQLite 元数据、Qdrant 存储和检索评测报告。
- **内置 UI 与鉴权**：`/ui/` 提供入库、检索、collection、文档、评测、健康检查页面；鉴权支持服务间 `X-API-Key` 和浏览器 session cookie。

## Docker 部署

推荐用 Docker Compose 部署。它会同时启动 QuillRAG 和本地 Qdrant，并持久化 Qdrant 数据、QuillRAG SQLite 元数据和模型缓存。运行配置来自 `.env`。

```bash
cp .env.example .env
# 至少编辑 .env：
#   EMBEDDING_API_KEY=...
# 可选：
#   MINERU_API_TOKEN=...
#   AUTH_ENABLED=true
#   AUTH_API_KEY=...
#   AUTH_PASSWORD_HASH=...
#   AUTH_SESSION_SECRET=...

bash deploy/docker-deploy.sh up
```

打开 [http://127.0.0.1:8001/ui/](http://127.0.0.1:8001/ui/)。

常用 Docker 运维命令：

```bash
bash deploy/docker-deploy.sh status
bash deploy/docker-deploy.sh logs
bash deploy/docker-deploy.sh health
bash deploy/docker-deploy.sh restart
bash deploy/docker-deploy.sh down
```

`reset` 会删除 Docker volume，清空本地 Qdrant 与元数据：

```bash
bash deploy/docker-deploy.sh reset
```

## 本地开发

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 如果只用 Docker 跑 Qdrant、本机跑 app：
# docker compose up -d qdrant
# 设置 QDRANT_URL=http://localhost:6333

uvicorn app.main:app --reload --port 8001
```

## API 一览

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | Qdrant、Embedder、Reranker 组件健康检查 |
| `/parse` | POST | 解析并分块文件或文本，不写入存储 |
| `/ingest` | POST | 解析、分块、向量化，写入 Qdrant 与 SQLite 元数据 |
| `/retrieve` | POST | 使用 `vector`、`bm25` 或 `hybrid` 检索 |
| `/rerank` | POST | 使用配置的 provider 对候选文档重排 |
| `/collections` | GET/POST | 查看或创建 collection |
| `/collections/{name}` | DELETE | 删除 collection |
| `/collections/{name}/documents` | GET | 查看 collection 下的文档 |
| `/collections/{name}/documents/{doc_id}` | DELETE | 删除单个文档 |
| `/collections/{name}/documents:batch-delete` | POST | 批量删除文档 |
| `/collections/{name}/prune-orphans` | POST | 清理没有元数据对应的 Qdrant points |
| `/evaluation/latest` | GET | 读取最近一次检索评测报告 |
| `/evaluation/run` | POST | 基于 JSONL golden set 运行检索评测 |
| `/ui/` | GET | 浏览器 UI |
| `/docs` | GET | Swagger UI |

## 配置

完整配置见 `.env.example`，实际加载逻辑在 `app/core/config.py`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8001` | HTTP 监听端口 |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 地址；Docker Compose 会覆盖为 `http://qdrant:6333` |
| `QDRANT_API_KEY` | 空 | Qdrant API Key；使用内置本地 Qdrant 时保持为空 |
| `EMBEDDING_PROVIDER` | `google` | `google` 或 `openai` |
| `EMBEDDING_BASE_URL` | Google Gemini API | Embedding API 地址 |
| `EMBEDDING_API_KEY` | 空 | 在线 embedding provider 必填 |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding 模型名 |
| `EMBEDDING_DIM` | `3072` | 创建 collection 时使用的向量维度 |
| `MINERU_API_TOKEN` | 空 | 启用 MinerU 云端 PDF 解析；为空时使用 PyMuPDF 兜底 |
| `RERANKER_ENABLED` | `false` | 是否启用重排 |
| `RERANKER_PROVIDER` | 代码默认 `local`，示例配置为 `flashrank` | 启用重排后可选 `flashrank`、`jina`、`llm`、`local` |
| `HYDE_ENABLED_BY_DEFAULT` | `false` | 是否默认启用 HyDE 查询改写 |
| `DEFAULT_CHUNK_SIZE` | `500` | 默认分块大小 |
| `DEFAULT_CHUNK_OVERLAP` | `50` | 默认分块重叠 |
| `DEFAULT_TOP_K` | `10` | 默认检索返回数量 |
| `METADATA_DB_PATH` | `data/rag_metadata.db` | SQLite 元数据路径 |
| `LOG_FORMAT` | `text` | `text` 或 `json` |
| `AUTH_ENABLED` | `false` | 公网部署时建议开启 |
| `AUTH_API_KEY` | 空 | 通过 `X-API-Key` 传入的服务间密钥 |
| `AUTH_USERNAME` | `admin` | 浏览器 UI 用户名 |
| `AUTH_PASSWORD_HASH` | 空 | UI 登录使用的 bcrypt 密码哈希 |
| `AUTH_SESSION_SECRET` | 空 | Cookie 签名密钥 |

## 架构

```text
HTTP -> AuthMiddleware -> RequestLoggingMiddleware
  -> /parse      -> parser/{MinerU, PyMuPDF, Markdown, Text} -> chunker -> cleaner
  -> /ingest     -> parse -> embed -> Qdrant + SQLite metadata + version history
  -> /retrieve   -> dense + sparse -> fusion -> diversity -> dedup
  -> /rerank     -> provider-pluggable reranker -> top-k
  -> /evaluation -> golden set runner -> JSON reports
```

更多细节见 [docs/architecture.md](docs/architecture.md)、[docs/api.md](docs/api.md)、[docs/deployment.md](docs/deployment.md)、[docs/evaluation.md](docs/evaluation.md)。

## 检索评测

内置指标包括 `recall@k`、`precision@k`、`MRR`、`NDCG@k` 和 `hit_rate`。

```bash
python scripts/eval_retrieval.py \
  --dataset fixtures/evaluation/retrieval.example.jsonl \
  --report-dir data/evaluation/reports
```

报告可通过 `/evaluation/latest` 读取。

## 测试

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

依赖真实 Qdrant 的测试使用 `integration` 标记。

## License

[MIT](LICENSE) © 2026 [ArtLjn](https://github.com/ArtLjn)

## 致谢

- [airQA / NSQA](https://github.com/ArtLjn/NSQA)
- [MinerU](https://mineru.net)
- [Qdrant](https://qdrant.tech)
- [BAAI](https://github.com/UKPLab)
- [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank)
