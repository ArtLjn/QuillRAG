# quillrag 架构

## 模块边界

```
┌──────────────────────────────────────────────────────────────────┐
│ quillrag (FastAPI, port 8001)                                 │
│                                                                  │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐       │
│  │ /parse  │  │ /ingest  │  │/retrieve │  │ /rerank     │       │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘       │
│       │            │             │               │              │
│       v            v             v               v              │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  services/（编排层）                                    │     │
│  │  parse_service / ingest_service / retrieve_service    │     │
│  │  rerank_service / collection_service / health_service │     │
│  └────┬──────────────┬───────────────┬────────────┬──────┘     │
│       │              │               │            │            │
│       v              v               v            v            │
│  ┌─────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────┐      │
│  │ parser/ │  │ retrieval/  │  │ storage/ │  │ models/ │      │
│  │         │  │             │  │          │  │         │      │
│  │ layout  │  │ embedder    │  │ qdrant   │  │ chunk   │      │
│  │ table   │  │ dense       │  │ metadata │  │ query   │      │
│  │ chunker │  │ sparse      │  │ version  │  │ document│      │
│  │ cleaner │  │ hybrid      │  │          │  │         │      │
│  │         │  │ reranker    │  │          │  │         │      │
│  │         │  │ hyde        │  │          │  │         │      │
│  └─────────┘  └─────────────┘  └──────────┘  └─────────┘      │
└──────────────────────────────────────────────────────────────────┘
        │                                  │
        v                                  v
   ┌──────────┐                      ┌──────────┐
   │ Tesseract│                      │  Qdrant  │
   │ (OCR)    │                      │ (vector) │
   └──────────┘                      └──────────┘
```

## 关键设计决策

### 1. 解析器与分块器分离
`parser` 只产生"碎片 chunks"（一个 layout element 对应一个 chunk），由 `chunker` 按策略做合并。这让 parser 不必关心分块策略，chunker 不必关心文件格式。

### 2. Embedder / Reranker 懒加载
模型在首次调用时后台线程加载，加载期间 `is_ready()=False`，`/health` 显示 `loading`。这避免服务启动阻塞 1-2 分钟。

### 3. 元数据独立 SQLite
不复用主系统 MySQL，自带 SQLite（`storage/metadata_store.py`），让 quillrag 可独立部署给其他项目复用。

### 4. 三种降级路径
- Qdrant 不可用 → 503（让主系统走无 RAG 分支）
- Embedder 不可用 → 自动切 bm25（次优但可用）
- Reranker 不可用 → 按原 score 排序（次优但可用）

降级原则：宁可次优也不要直接失败。

### 5. RRF 融合默认权重
`vector_weight=0.7 + sparse_weight=0.3`，可通过环境变量调整。长查询调高 vector 到 0.8，含错误码的查询调高 sparse 到 0.5。

## 扩展点

| 扩展 | 实现位置 | 说明 |
| --- | --- | --- |
| 替换 PDF 版面分析为 LayoutLMv3 / PP-Structure | `app/parser/layout/analyzer.py` | 接口已抽象，替换 `analyze_page` 即可 |
| 自训练 Embedding | `app/retrieval/embedder.py` | 替换 sentence-transformers 加载逻辑 |
| 多租户 | `app/services/collection_service.py` | 暂未实现，展望章节 |
| 评估平台 | `app/evaluation/`（预留目录） | P2 范围 |
| 知识图谱 | （未实现） | 已与导师澄清暂搁置 |

## 性能参考

| 操作 | 单次延迟（CPU，4 核） |
| --- | --- |
| `/parse` MD 1万字 | < 200ms |
| `/parse` PDF 10 页 | ~2s（含 OCR） |
| `/ingest` 同上 + Embedding | 加 100-300ms |
| `/retrieve` hybrid top10 | 200-500ms（Embedder 已加载） |
| `/rerank` top5 from 20 | 600-1000ms |

毕设演示数据规模（千级 chunk）下完全可用。
