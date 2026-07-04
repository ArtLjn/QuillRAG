# quillrag 部署指南

## 单机部署（推荐毕设演示场景）

最低配置：4 核 8G，能同时承载 quillrag + Qdrant + 主系统。

### 步骤

1. 克隆与配置

   ```bash
   cd /path/to/finished
   # 假设 quillrag/ 已就位
   cd quillrag
   cp .env.example .env
   # 如需调整模型 / 端口，编辑 .env
   ```

2. 启动双服务

   ```bash
   docker-compose up -d
   ```

   等待 30-60 秒（首次启动会拉取 BAAI/bge-large-zh-v1.5 与 bge-reranker-v2-m3 模型，约 2GB）。

3. 验证健康

   ```bash
   curl http://localhost:8001/health
   ```

   预期返回 `{status: "ok", components: {...}}`。若 `status=degraded`，查看 `docker-compose logs quillrag` 定位。

4. 创建 collection 与入库

   ```bash
   # 创建 collection
   curl -X POST http://localhost:8001/collections \
     -H "Content-Type: application/json" \
     -d '{"name": "ticket_knowledge", "vector_dim": 1024, "distance": "Cosine"}'

   # 入库 Markdown 文档
   curl -X POST http://localhost:8001/ingest \
     -F collection=ticket_knowledge \
     -F text@- <<'EOF'
   # 工单处理
   普通工单 24 小时内响应。
   ## 紧急工单
   紧急工单 2 小时内响应。
   EOF

   # 检索
   curl -X POST http://localhost:8001/retrieve \
     -H "Content-Type: application/json" \
     -d '{"query": "紧急工单多久响应", "collection": "ticket_knowledge", "mode": "hybrid"}'
   ```

## 资源占用预估

| 组件 | 内存 | 说明 |
| --- | --- | --- |
| Qdrant | ~500MB | 毕设 demo 数据（万级 chunk） |
| quillrag | ~500MB | Embedding 走 HTTP 不占内存 |
| quillrag + Reranker 模型 | ~2GB | bge-reranker-v2-m3（首次调用时懒加载） |
| 主系统 ai-agent-learning | ~1GB | 不含主系统 LLM 调用 |

合计 4 核 4G 可承载（Reranker 未触发时）；Reranker 触发后峰值约 6G。

## 模型预下载

Embedding 走在线 Google API，无需本地权重。Reranker 仍为本地 Cross-Encoder，Dockerfile 已包含预下载：

```bash
# 本地开发预热 reranker 缓存
python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"
```

缓存目录可通过 `HF_HOME` 环境变量调整。

## OCR 系统依赖

PDF 解析中的 OCR 兜底依赖 Tesseract，必须安装中文语言包：

| 系统 | 命令 |
| --- | --- |
| macOS | `brew install tesseract tesseract-lang` |
| Ubuntu/Debian | `apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra` |
| Alpine | `apk add tesseract-ocr tesseract-ocr-data-chi_sim` |

Docker 镜像已在 Dockerfile 中安装。

## 与主系统联调

主系统侧通过 `tools/rag_client.py` HTTP 调用（待实现）：

```python
# 主系统端代码示例（下一个 change 实现完整 client）
import httpx

class RagClient:
    def __init__(self, base_url: str = "http://localhost:8001", timeout: int = 10):
        self.base_url = base_url
        self.timeout = timeout

    async def retrieve(self, query: str, collection: str, mode: str = "hybrid"):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/retrieve",
                json={"query": query, "collection": collection, "mode": mode},
            )
            response.raise_for_status()
            return response.json()
```

主系统降级策略：超时 / 5xx / `/health` degraded → 走「无 RAG 增强」分支（详见主系统 design-spec 第 13 章）。

## 排查清单

| 现象 | 排查方向 |
| --- | --- |
| `/health` qdrant=unavailable | 检查 Qdrant 容器：`docker-compose logs qdrant` |
| `/retrieve` 慢 | 看 quillrag 日志，确认 Embedder 已加载；考虑关闭 HyDE |
| `/ingest` 503 | Qdrant 不可用或网络分区 |
| `/parse` 422 PARSE_FAILED | PDF 文件损坏，或 PyMuPDF 未正确安装 |
| OCR 中文乱码 | tesseract-ocr-chi-sim 未装 |

## 数据卷与备份

- Qdrant 数据：docker volume `qdrant_data`，备份用 `docker run --rm -v qdrant_data:/data -v $(pwd):/backup alpine tar czf /backup/qdrant.tar.gz /data`
- SQLite 元数据：`quillrag/data/rag_metadata.db`（容器内路径，建议挂载到 host）

## 关停与回滚

```bash
docker-compose down        # 停服务，保留数据
docker-compose down -v     # 停服务并删除数据卷（清空所有知识库）
```
