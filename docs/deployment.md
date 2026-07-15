# QuillRAG 部署指南

本文档对应当前仓库的 Dockerfile、docker-compose.yml 和 deploy 脚本。

## 推荐方式：Docker Compose

Docker Compose 会启动两个服务：

- `quillrag`：FastAPI 应用，监听 `8001`
- `qdrant`：本地 Qdrant，监听 `6333` / `6334`

持久化数据：

- `qdrant_data`：Qdrant 向量数据
- `quillrag_data`：SQLite 元数据与 FlashRank 缓存
- `hf_cache`：Hugging Face / transformers 缓存

### 首次部署

```bash
cp .env.example .env
```

至少填写：

```dotenv
EMBEDDING_API_KEY=...
```

公网部署建议同时开启鉴权：

```dotenv
AUTH_ENABLED=true
AUTH_API_KEY=...
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=...
AUTH_SESSION_SECRET=...
```

启动：

```bash
bash deploy/docker-deploy.sh up
```

访问：

- UI：http://127.0.0.1:8001/ui/
- Swagger：http://127.0.0.1:8001/docs
- 健康检查：http://127.0.0.1:8001/health

### 常用命令

```bash
bash deploy/docker-deploy.sh status
bash deploy/docker-deploy.sh logs
bash deploy/docker-deploy.sh qdrant-logs
bash deploy/docker-deploy.sh health
bash deploy/docker-deploy.sh restart
bash deploy/docker-deploy.sh down
```

删除所有本地容器数据：

```bash
bash deploy/docker-deploy.sh reset
```

## 本地开发部署

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

如果本机跑 app、Docker 只跑 Qdrant：

```bash
docker compose up -d qdrant
```

`.env` 中使用：

```dotenv
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

启动应用：

```bash
uvicorn app.main:app --reload --port 8001
```

## 运行配置

关键配置来源：

- `.env.example`：完整配置模板
- `app/core/config.py`：默认值与类型
- `docker-compose.yml`：容器部署覆盖项

Docker Compose 会强制覆盖：

```yaml
QDRANT_URL: http://qdrant:6333
METADATA_DB_PATH: /app/data/rag_metadata.db
RERANKER_FLASHRANK_CACHE_DIR: /app/data/flashrank_cache
```

因此复制 `.env.example` 后，不需要为内置 Qdrant 填 `QDRANT_API_KEY`。

## 重排器选择

默认 `RERANKER_ENABLED=false`，不会加载重排模型。

开启方式：

```dotenv
RERANKER_ENABLED=true
RERANKER_PROVIDER=flashrank
```

可选 provider：

| Provider | 说明 | 适用场景 |
| --- | --- | --- |
| `flashrank` | 本地 ONNX 推理，模型约 18-120MB | 轻量生产部署 |
| `jina` | 在线 Jina rerank API | 不想维护本地模型 |
| `llm` | OpenAI 兼容 LLM 网关打分 | 复用主系统 LLM |
| `local` | `BAAI/bge-reranker-v2-m3`，模型较大 | 实验或精度对比 |

## OCR 系统依赖

Docker 镜像已安装 Tesseract OCR 和中文语言包。本地开发需要自行安装：

| 系统 | 命令 |
| --- | --- |
| macOS | `brew install tesseract tesseract-lang` |
| Ubuntu/Debian | `apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra` |
| Alpine | `apk add tesseract-ocr tesseract-ocr-data-chi_sim` |

## 健康检查语义

`/health` 返回 HTTP 200，并在 body 中体现整体状态：

- `ok`：可用
- `degraded`：存在 `failed` 或 `unavailable` 组件

组件状态：

- `ok`：组件就绪
- `idle`：懒加载未触发，属于正常状态
- `loading`：后台加载中
- `disabled`：用户主动关闭，常见于默认重排器
- `failed` / `unavailable`：需要排查

## 排查清单

| 现象 | 排查方向 |
| --- | --- |
| `/health` 中 `qdrant=unavailable` | `bash deploy/docker-deploy.sh qdrant-logs` |
| `/health` 中 `embedder=failed` | 检查 `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、网络连通性 |
| `/retrieve` 返回降级 warning | 查看 `actual_mode` 与日志，确认 vector/BM25 是否有一侧失败 |
| `/ingest` 失败 | 检查 Qdrant collection 维度是否等于 `EMBEDDING_DIM` |
| PDF 解析质量低 | 配置 `MINERU_API_TOKEN`，或检查 OCR 依赖 |
| UI 无法登录 | 确认 `AUTH_PASSWORD_HASH` 和 `AUTH_SESSION_SECRET` 已配置 |

## systemd 脚本

`deploy/install.sh`、`deploy/server-sync.sh`、`deploy/server-ctl.sh` 保留用于远程 systemd 部署场景。新部署优先使用 Docker Compose；只有需要接入已有服务器 Python 环境时再使用 systemd 脚本。
