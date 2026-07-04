# quillrag API 契约

> 版本：v0.1.0
> 所有接口走 JSON，文件上传走 multipart
> 返回体统一结构 `{code, message, data, warning?, error_code?}`
>
> 默认对接：Embedding Google gemini-embedding-001（dim=3072）+ Qdrant（dense Cosine + sparse BM25）+ 本地 Reranker BAAI/bge-reranker-v2-m3
> 部署时与主系统 `config.yaml` 共用同一套 Qdrant / Embedding / LLM 凭证

## 通用响应

### 成功

```json
{
  "code": "OK",
  "message": "ok",
  "data": { ... },
  "warning": null
}
```

### 失败

```json
{
  "code": "FAILED",
  "message": "解析失败",
  "data": null,
  "warning": null,
  "error_code": "PARSE_FAILED"
}
```

### 降级（HTTP 200 + warning 字段）

```json
{
  "code": "OK",
  "message": "ok",
  "data": { ... },
  "warning": "vector_to_bm25_fallback"
}
```

## POST /parse

仅解析与分块，不写入向量库。用于调用方预览分块效果，或调试分块策略。

### 请求

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 二选一 | 原始文档（PDF 上传文件） |
| `text` | string | 二选一 | TXT / MD 可直接传文本 |
| `file_type` | string | 否 | `pdf` / `md` / `txt`；未传则按 filename/content-type 推断 |
| `strategy` | string | 否 | `semantic` / `fixed` / `structure_aware` |
| `chunk_size` | int | 否 | 仅 `fixed` 生效，默认 500 |
| `chunk_overlap` | int | 否 | 默认 50 |
| `source` | string | 否 | 文档来源标识 |
| `category` | string | 否 | 业务类别 |

### 响应

```json
{
  "code": "OK",
  "message": "ok",
  "data": {
    "doc_id": "c7fe3f506aa2",
    "chunks": [
      {
        "content": "...",
        "metadata": {
          "source": "...",
          "page": 1,
          "category": "paragraph",
          "heading_path": ["标题A"],
          "doc_id": "c7fe3f506aa2",
          "chunk_index": 0
        }
      }
    ],
    "layout_summary": {
      "title": 3,
      "paragraph": 5,
      "table": 1,
      "total": 9
    }
  }
}
```

### 错误码

| HTTP | error_code | 触发条件 |
| --- | --- | --- |
| 400 | UNSUPPORTED_FORMAT | 未提供 file/text，或格式不支持 |
| 422 | PARSE_FAILED | 解析过程异常（PDF 损坏等） |
| 507 | MODEL_UNAVAILABLE | OCR / 版面模型加载失败 |

## POST /ingest

完整链路：解析 → 分块 → 向量化 → 写入 Qdrant + SQLite。

### 请求

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `collection` | string | 是 | 目标 collection |
| `file` / `text` | file / string | 二选一 | 同 /parse |
| `file_type` | string | 否 | 同 /parse |
| `strategy` | string | 否 | 同 /parse |
| `chunk_size` / `chunk_overlap` | int | 否 | 同 /parse |
| `source` | string | 否 | 同 /parse |
| `category` | string | 否 | 同 /parse |

### 响应

```json
{
  "code": "OK",
  "data": {
    "doc_id": "...",
    "chunk_count": 12,
    "collection": "ticket_knowledge",
    "action": "created"
  }
}
```

`action` 取值：`created`（新文档） / `updated`（覆盖旧版本） / `noop`（content_hash 未变，跳过）。

### 错误码

| HTTP | error_code | 触发条件 |
| --- | --- | --- |
| 404 | COLLECTION_NOT_FOUND | 指定 collection 不存在 |
| 422 | INGEST_FAILED | 解析/写入异常 |
| 503 | QDRANT_UNAVAILABLE | Qdrant 不可达 |

## POST /retrieve

### 请求

```json
{
  "query": "用户问题",
  "collection": "ticket_knowledge",
  "mode": "hybrid",
  "top_k": 10,
  "filters": {"category": "technical"},
  "use_hyde": false
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 是 | 查询语句 |
| `collection` | string | 是 | 目标 collection |
| `mode` | string | 否 | `vector` / `bm25` / `hybrid`，默认 `hybrid` |
| `top_k` | int | 否 | 默认 10，最大 100 |
| `filters` | object | 否 | 元数据等值过滤 |
| `use_hyde` | bool | 否 | 是否启用 HyDE 查询改写，默认 false |

### 响应

```json
{
  "code": "OK",
  "data": {
    "results": [
      {
        "content": "...",
        "score": 0.92,
        "doc_id": "...",
        "chunk_index": 0,
        "metadata": {...}
      }
    ],
    "actual_mode": "hybrid",
    "query_vector_dim": 1024
  },
  "warning": null
}
```

`actual_mode` 反映实际生效的模式（可能因降级与请求的 mode 不同）。

### 错误码

| HTTP | error_code | 触发条件 |
| --- | --- | --- |
| 400 | INVALID_MODE | mode 不是 vector/bm25/hybrid |
| 503 | QDRANT_UNAVAILABLE | Qdrant 不可达 |

### 降级规则

| 触发 | 实际行为 |
| --- | --- |
| `mode=vector` + Embedder 不可用 | `actual_mode=bm25`，`warning=vector_to_bm25_fallback` |
| `mode=hybrid` + Embedder 不可用 | `actual_mode=bm25`，`warning=hybrid_to_bm25_fallback` |
| `use_hyde=true` 但未配置 LLM | 用原 query 检索，`warning=hyde_not_configured` |

## POST /rerank

### 请求

```json
{
  "query": "...",
  "documents": ["doc1", "doc2", {"content": "doc3", "source": "..."}],
  "top_k": 5,
  "model": "BAAI/bge-reranker-v2-m3"
}
```

`documents` 元素可以是字符串或 dict（dict 中 `content` / `text` 字段为正文，其余作为 metadata 透传）。

### 响应

```json
{
  "code": "OK",
  "data": {
    "results": [
      {"content": "...", "score": 0.95, "original_index": 2, "metadata": {}}
    ]
  },
  "warning": null
}
```

### 错误码

| HTTP | error_code | 触发条件 |
| --- | --- | --- |
| 507 | RERANKER_MODEL_UNAVAILABLE | 模型无法加载且无原 score 可降级（极小概率） |

降级：模型不可用时按原顺序返回，`warning=reranker_degraded`。

## POST /collections

```json
{"name": "ticket_knowledge", "vector_dim": 1024, "distance": "Cosine"}
```

## GET /collections

返回所有 collection 列表：

```json
{"code": "OK", "data": [{"name": "...", "points_count": N, "status": "GREEN"}]}
```

## DELETE /collections/{name}

删除 collection 及其 SQLite 元数据。

## GET /collections/{name}/documents?page=1&page_size=20

分页查询 collection 内文档。

## DELETE /collections/{name}/documents/{doc_id}

删除指定文档（同步清理 Qdrant points 与 SQLite 记录）。

## GET /health

```json
{
  "status": "ok",
  "components": {
    "qdrant": "ok",
    "embedder": "ok",
    "reranker": "ok"
  },
  "warning": null
}
```

任一组件不可用 → `status=degraded`，对应组件状态为 `unavailable` 或 `loading`。HTTP 恒为 200，由调用方决定是否走降级分支。
