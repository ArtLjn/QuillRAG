# quillrag 上线前验证 SOP

> 本文档对应 tasks.md Group 14.3-14.7，依赖真实 Docker + Qdrant + 模型权重。
> 在 macOS/Linux 主机执行；预计耗时 30-60 分钟（首次拉模型较慢）。

## 前置条件

- Docker 24+ 与 docker-compose
- 至少 8GB 可用内存（quillrag ~4GB + Qdrant ~500MB + 主系统 ~1GB）
- 网络可访问 Docker Hub 与 HuggingFace（首次拉模型约 2GB）

## 14.3 docker-compose 启动

```bash
cd quillrag
cp .env.example .env
docker-compose up -d
sleep 60  # 等待模型首次加载
curl http://localhost:8001/health
```

**期望**：
- HTTP 200
- `status=ok` 或 `degraded`（首次启动时 reranker 可能还在 loading）
- `components.qdrant=ok`、`components.embedder=ok`

**排查**：
- `docker-compose logs quillrag` 查看 Embedder/Reranker 加载日志
- `docker-compose logs qdrant` 查看向量库启动情况

## 14.4 灌入毕设演示 PDF

准备 10 篇 PDF（建议放在 `quillrag/fixtures/` 下）：

```bash
# 创建 collection
curl -X POST http://localhost:8001/collections \
  -H "Content-Type: application/json" \
  -d '{"name": "ticket_knowledge", "vector_dim": 1024, "distance": "Cosine"}'

# 批量入库（示例循环）
for pdf in fixtures/*.pdf; do
  echo "Ingesting $pdf..."
  curl -X POST http://localhost:8001/ingest \
    -F collection=ticket_knowledge \
    -F "file=@$pdf" \
    -F strategy=structure_aware
done

# 查询入库情况
curl http://localhost:8001/collections/ticket_knowledge/documents | jq .
```

**期望**：
- 每篇 PDF 入库返回 `chunk_count > 0`
- `/collections/ticket_knowledge/documents` 列出 10 条文档记录
- `/parse` 单独测试某篇 PDF 的分块效果

## 14.5 Qdrant 不可用降级

```bash
docker-compose stop qdrant
sleep 5

# /retrieve 应返回 503
curl -X POST http://localhost:8001/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "测试", "collection": "ticket_knowledge", "mode": "hybrid"}'
# 期望：HTTP 503，error_code=QDRANT_UNAVAILABLE

# /health 应返回 degraded
curl http://localhost:8001/health
# 期望：status=degraded，components.qdrant=unavailable

docker-compose start qdrant
```

## 14.6 Embedder 不可用降级

模拟方式：临时把模型缓存目录改名，让 embedder 加载失败。

```bash
docker-compose exec quillrag mv /opt/hf-cache /opt/hf-cache.bak

# 触发新进程加载 embedder（重启服务）
docker-compose restart quillrag
sleep 30

# /retrieve mode=vector 应自动降级为 bm25
curl -X POST http://localhost:8001/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "测试", "collection": "ticket_knowledge", "mode": "vector"}'
# 期望：HTTP 200，data.actual_mode=bm25，warning 含 vector_to_bm25_fallback

# 恢复
docker-compose exec quillrag mv /opt/hf-cache.bak /opt/hf-cache
docker-compose restart quillrag
```

## 14.7 性能验证

```bash
# 1000 chunk 规模下，单次 /retrieve + /rerank 应 < 2 秒
time curl -X POST http://localhost:8001/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "工单处理流程", "collection": "ticket_knowledge", "mode": "hybrid", "top_k": 20}'

time curl -X POST http://localhost:8001/rerank \
  -H "Content-Type: application/json" \
  -d '{"query": "工单处理流程", "documents": ["...20 条..."], "top_k": 5}'
```

**期望**：
- `/retrieve hybrid top_k=20`：CPU 4 核下 < 1 秒（Embedder 已加载）
- `/rerank top_k=5 from 20`：CPU 4 核下 < 1.5 秒

**性能不达标排查**：
- 检查 `docker stats` 容器 CPU/内存是否打满
- Embedder 是否仍处于 loading 状态（`/health` 查看）
- Qdrant collection 是否使用了 HNSW 索引（默认开启）

## 验证完成清单

- [ ] 14.3 docker-compose 启动，/health 返回 ok
- [ ] 14.4 10 篇 PDF 全部入库成功
- [ ] 14.5 Qdrant 停止时 /retrieve 503, /health degraded
- [ ] 14.6 Embedder 不可用时 /retrieve 自动降级为 bm25
- [ ] 14.7 单次检索 + 重排 < 2 秒

每项验证完成后，在 `openspec/changes/add-quillrag-project/tasks.md` 对应行勾选。
