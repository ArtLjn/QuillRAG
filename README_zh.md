<p align="center">
  <img src="docs/banner.svg" alt="QuillRAG" width="100%"/>
</p>

<p align="center">
  <a href="README_zh.md">简体中文</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/ArtLjn/QuillRAG"><img alt="tests" src="https://img.shields.io/badge/测试-167%2F167-brightgreen.svg"/></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg"/></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue.svg"/></a>
  <a href="https://fastapi.tiangolo.com"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg"/></a>
  <a href="https://qdrant.tech"><img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-1.11%2B-dc382d.svg"/></a>
</p>

# QuillRAG · 独立 RAG 服务

**QuillRAG** 是一个开箱即用的检索增强生成（RAG）服务，提供工业级 PDF 解析、混合检索、Cross-Encoder 重排，HTTP API 一键接入主系统 LLM。

借鉴 [airQA / NSQA](https://github.com/ArtLjn/NSQA) 项目的学术级检索模式，浓缩为可独立部署的服务。

## ✨ 核心能力

- **PDF 复杂解析** — MinerU 云端 API（SOTA，在线）+ PyMuPDF 启发式降级（离线）。表格、公式、图片、双栏、页眉页脚全覆盖。
- **混合检索** — Dense + Sparse (BM25) 融合，支持 RRF 与 MinMax 归一化 + 同文档多样性衰减。
- **5 选 1 重排** — `disabled` / `flashrank`（本地 ONNX，18-120MB）/ `jina`（免费 1M token/月）/ `llm`（任意 OpenAI 兼容）/ `local`（BAAI bge-reranker-v2-m3）。
- **超越纯文本** — 表格序列化为 `key=value`（BM25 可按字段查表），公式 LaTeX → Unicode（`\alpha` → α）让稀疏检索也能命中。
- **生产就绪** — 模型懒加载（idle/ok/failed 健康语义）、`request_id` 全链路追踪、慢请求告警、JSON/text 双格式日志。
- **内置鉴权** — `X-API-Key` 头（服务间）+ 用户名密码登录（浏览器 UI）。
- **实时 UI** — `/ui/` TailwindCSS 仪表盘，入库 / 检索 / 浏览 chunk 零前端构建。

## 📦 API 一览

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | 健康检查（Qdrant / Embedder / Reranker 状态）— 公开 |
| `/parse` | POST | 解析文档 → 预览分块（不入库） |
| `/ingest` | POST | 解析 + 分块 + 向量化 + 写入 Qdrant |
| `/retrieve` | POST | 三模式检索（vector / bm25 / hybrid） |
| `/rerank` | POST | Cross-Encoder 对候选精排 |
| `/collections` | GET/POST/DELETE | Collection 与文档管理 |
| `/ui/` | GET | Web UI（开启鉴权时需登录） |
| `/docs` | GET | Swagger 文档（生产环境需鉴权） |

## 🚀 快速开始

```bash
git clone https://github.com/ArtLjn/QuillRAG.git
cd QuillRAG
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 填入：QDRANT_URL/API_KEY、EMBEDDING_API_KEY、可选 MINERU_API_TOKEN

uvicorn app.main:app --reload --port 8001
```

打开 [http://127.0.0.1:8001/ui/](http://127.0.0.1:8001/ui/)

## 🔧 关键配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8001` | HTTP 监听端口 |
| `QDRANT_URL` / `QDRANT_API_KEY` | — | Qdrant 地址 |
| `EMBEDDING_PROVIDER` | `google` | `google` / `openai` |
| `EMBEDDING_API_KEY` | — | Google gemini 或 OpenAI key |
| `EMBEDDING_DIM` | `3072` | gemini-embedding-001 维度 |
| `MINERU_API_TOKEN` | — | https://mineru.net 注册免费 100 页/天 |
| `RERANKER_PROVIDER` | `flashrank` | `disabled` / `flashrank` / `jina` / `llm` / `local` |
| `AUTH_ENABLED` | `false` | 是否开启鉴权（公网部署推荐开） |
| `AUTH_API_KEY` | — | 服务间调用 Bearer token |

完整配置见 [`docs/deployment.md`](docs/deployment.md)。

## 🏗 架构

```
HTTP → AuthMiddleware → RequestLoggingMiddleware
  → /parse  → parser/{MinerU,PyMuPDF,Markdown,Text} → chunker → cleaner
  → /ingest → parse → embed → Qdrant + SQLite metadata + 版本历史
  → /retrieve → dense + sparse → RRF/MinMax 融合 → diversity → dedup
  → /rerank → Cross-Encoder（provider 可插拔）→ top-k
```

借鉴 airQA 的模块：
- MinerU 客户端（HTTP 上传 + 轮询 + zip 解析）
- BlockType 常量字典（50+ 类型）与 category 映射
- LaTeX 规范化 + Unicode 符号映射
- 双栏阅读顺序还原（x0 聚类）
- 公式 / 表格 / 图空间距离语义锚点
- `logic_idx` 全局阅读顺序 + prev/next 邻居窗口

详见 [`docs/architecture.md`](docs/architecture.md)。

## 📊 评估指标

内置检索评测：`recall@k` / `precision@k` / `MRR` / `NDCG@k` / `hit_rate`。
使用 `scripts/eval_retrieval.py` 对 JSONL golden set 一键评测，并可通过 `/evaluation/latest` 读取最新报告。
详见 [`docs/evaluation.md`](docs/evaluation.md)。

## 📄 License

[MIT](LICENSE) © 2026 [ArtLjn](https://github.com/ArtLjn)

## 🙏 致谢

- [airQA / NSQA](https://github.com/ArtLjn/NSQA) — 学术级 RAG 模式
- [MinerU](https://mineru.net) — SOTA PDF 解析
- [Qdrant](https://qdrant.tech) — 向量数据库
- [BAAI](https://github.com/UKPLab) — bge embedding / reranker 模型
- [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank) — ONNX 重排器
