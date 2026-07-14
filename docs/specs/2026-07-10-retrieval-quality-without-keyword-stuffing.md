# QuillRAG 检索质量优化方案：避免堆词库式提分

## 背景

当前评测页面显示 `ticket_knowledge` 数据集存在一批未命中样本，集中在 ITSM 场景下的短问句和流程判断题，例如安全事件、DNS、HTTPS 证书、负载均衡、MFA、CVE、容量评估、索引同步等。

这些问题如果只通过给知识库追加同义词、标签、常见问法来提升命中率，短期可能拉高 golden set 指标，但会让知识库逐渐变成“召回诱饵”，而不是可信事实来源。这类优化容易导致系统过拟合当前字段和评测集，后续真实用户问法变化时效果不稳定，也会污染 AI 回答依据。

本方案的目标是：保持知识库内容干净，把优化重点放在检索链路、排序链路、chunk 结构、置信度判断和评测诊断上。

## 目标

- 提升 `Recall@5`、`Recall@10`、`Hit Rate` 和 `MRR`。
- 不通过向知识库正文堆砌关键词、同义词、伪问法来提分。
- 能解释每个未命中样本失败在哪一层：dense、sparse、hybrid、rerank、chunk、入库或 golden set。
- 让系统在低置信度时明确返回“不确定/未找到可靠知识”，而不是强答。
- 形成可复现实验闭环，每次优化只改一个变量并记录指标变化。

## 非目标

- 不把同义词、别名、常见问法批量写进知识库原文。
- 不为了当前 52 条 golden set 手工定制规则。
- 不把召回失败简单归因于 embedding 模型不够好。
- 不在没有诊断数据的情况下盲目调 `top_k`、权重或阈值。

## 当前关键观察

当前项目已经具备以下基础能力：

- `/evaluation/run` 可以基于 golden set 计算 `Recall@K`、`Precision@K`、`MRR`、`NDCG`、`Hit Rate`。
- `hybrid_searcher` 已经做 dense + sparse 双路召回，并在内部使用 `max(top_k * 2, 20)` 扩大候选。
- `retrieve_service` 支持 `vector`、`bm25`、`hybrid` 三种模式，并能在 embedder 不可用时降级到 BM25。
- `reranker` 已实现多 provider，但评测链路目前没有把“扩大候选后再 rerank”作为标准实验路径。
- `sparse_searcher` 当前使用 Python 内置 `hash(token)` 生成 sparse index，这会受到 Python hash 随机盐影响，服务重启后入库 token index 和查询 token index 可能不一致。

其中，`hash(token)` 是优先级最高的正确性问题。它不是调参，也不是堆词，而是 sparse 检索可重复性的基础。

## 外部实践参考

调研主流 RAG 工程实践后，可以看到一个共同方向：**不污染 source document，而是在 source document 外构建可解释、可重建、可评测的 retrieval layer**。

### 1. Advanced RAG：分 ingestion、inference、evaluation 三段优化

Microsoft 的 Advanced RAG 文档把生产级 RAG 拆成 ingestion、inference pipeline、evaluation 三个阶段。它强调 chunking strategy、chunking organization、query preprocessing、query router、post-retrieval re-ranking 和 golden dataset 评估。

对 QuillRAG 的启发：

- 不要只看最终回答，要能追踪每次回答用了哪些 chunk。
- chunking 和 index organization 本身就是优化对象。
- query rewriting、query router、rerank 都应该在检索链路完成，不应该写回知识库原文。
- 如果使用“sample question for each chunk”这类 alignment optimization，必须作为派生索引或训练样本，而不是污染原始知识库。

参考：[Build advanced retrieval-augmented generation systems](https://learn.microsoft.com/en-us/azure/developer/ai/advanced-retrieval-augmented-generation)

### 2. Hybrid + RRF：融合不同召回器，而不是统一分数

Elasticsearch 官方文档介绍的 Reciprocal Rank Fusion 用于合并多个 relevance indicator 的结果集，不要求不同召回器的分数在同一量纲。它适合 dense 和 sparse 同时存在的场景。

对 QuillRAG 的启发：

- dense 和 sparse 各自扩大候选，再用 RRF 或 MinMax 融合。
- 对比 RRF 和当前 MinMax 加权融合的效果。
- 不把优化变成“给 sparse 喂更多词”，而是让不同召回器互补。

参考：[Elasticsearch Reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)

### 3. Two-stage retrieval：多召回，少喂给 LLM

Pinecone 的 reranker 实践强调，两阶段检索的目标是先提高 retrieval recall，再通过 reranker 缩小进入 LLM 的上下文。它也提醒不能简单把更多文档塞进上下文窗口，因为这会伤害 LLM 在上下文中的定位能力。

对 QuillRAG 的启发：

- 第一阶段：`dense top50 + sparse top50` 提升候选覆盖率。
- 第二阶段：`hybrid top30 -> rerank top10` 提升排序质量。
- 最终给主系统 LLM 的内容仍然保持少而准。

参考：[Rerankers and Two-Stage Retrieval](https://www.pinecone.io/learn/series/rag/rerankers/)

### 4. HyDE / query rewriting：只改查询，不改文档

HyDE 和 Rewrite-Retrieve-Read 都属于查询侧增强。HyDE 通过 LLM 生成假设文档再向量检索，Rewrite-Retrieve-Read 则让 query 更适合 retriever。

对 QuillRAG 的启发：

- 可以对口语化 query 做 rewrite、step-back 或 HyDE。
- 这些生成内容只在查询时使用，不写入知识库。
- 需要把 rewrite 前后的 query、命中变化记录进评测报告，避免不可解释。

参考：[HyDE paper](https://arxiv.org/abs/2212.10496)、[Rewrite-Retrieve-Read paper](https://arxiv.org/abs/2305.14283)

### 5. Sentence window / small-to-big：检索粒度和回答粒度分离

Haystack 的 SentenceWindowRetriever 先检索小句子，再取相邻句子作为完整上下文。Microsoft 文档也提到 Small2Big 思路：可以先按句子检索，再提供附近句子或完整段落给 LLM。

对 QuillRAG 的启发：

- 小 chunk 用于召回，大 chunk 或邻居窗口用于回答。
- 需要利用现有 `logic_idx`、`prev_view_id`、`next_view_id` 或新增 parent metadata。
- 这解决的是上下文粒度问题，不需要给原文堆关键词。

参考：[Haystack SentenceWindowRetriever](https://docs.haystack.deepset.ai/docs/sentencewindowretrieval)

### 6. RAPTOR：摘要树是派生索引，不是原文污染

RAPTOR 通过递归聚类和摘要构建 tree-organized retrieval，让查询既能命中细粒度 chunk，也能命中高层摘要。

对 QuillRAG 的启发：

- 可以考虑为长文档构建摘要索引层。
- 摘要必须带 provenance，能追溯到原始 chunk。
- 摘要层应该可重建、可关闭、可单独评测，不能覆盖原始事实。

参考：[RAPTOR paper](https://arxiv.org/abs/2401.18059)

## 优化原则

### 1. 知识库保持事实干净

知识库应该存事实、流程、约束和证据，不应该为了召回而塞大量关键词。检索层可以理解 query、扩大候选、重排、判断置信度，但不要把这些策略污染到知识内容里。

### 2. 先诊断，再优化

未命中样本至少要能回答：

- 相关 chunk 是否出现在 dense top50？
- 相关 chunk 是否出现在 sparse top50？
- 相关 chunk 是否出现在 hybrid top50？
- 相关 chunk 是否只是没有排进 top10？
- 相关 chunk 是否根本没有入库？
- golden set 标注是否和实际 chunk 编号一致？

如果相关 chunk 在 top50 里，问题主要是排序；如果 top50 都没有，问题才是召回、chunk 或入库。

### 3. 优先优化机制，不优化语料投机性

可接受的优化：

- 稳定 sparse token hash。
- 扩大 candidate set。
- 引入 rerank。
- 调整 chunk 结构。
- 使用父子 chunk 检索。
- 做 query intent routing。
- 做置信度校准。
- 增强评测报告的 failure analysis。

谨慎或禁止的优化：

- 在知识库正文中批量堆同义词。
- 给每条知识追加大量“可能问法”。
- 为单个 golden set 样本硬编码规则。

## 方案设计

### 阶段一：评测诊断增强

扩展 `app/evaluation/runner.py`，为每个样本记录分层召回诊断。

建议新增字段：

```json
{
  "query": "...",
  "relevant": ["itsm-tls-certificate#0"],
  "hit": false,
  "diagnostics": {
    "dense_top50_hit": false,
    "sparse_top50_hit": true,
    "hybrid_top50_hit": true,
    "final_top10_hit": false,
    "failure_stage": "ranking"
  }
}
```

`failure_stage` 建议取值：

- `dense_missing`：dense topN 未召回，但 sparse 或 hybrid 可能召回。
- `sparse_missing`：sparse topN 未召回，但 dense 可能召回。
- `retrieval_missing`：dense、sparse、hybrid topN 都未召回。
- `ranking`：候选集中出现过，但最终 topK 没命中。
- `golden_or_ingest`：相关 doc_id/chunk_index 不存在或无法匹配。

这样可以把“未命中样本列表”升级成“可行动的失败分类”。

### 阶段二：修复 sparse 稳定性

将 `app/retrieval/sparse_searcher.py` 中的 Python 内置 `hash(token)` 替换为稳定 hash，例如基于 `hashlib.md5`：

```python
def _hash_index(token: str) -> int:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % (2**31)
```

这会保证：

- 同一 token 在不同进程、不同重启后 index 一致。
- 入库 sparse vector 和查询 sparse vector 可稳定对齐。
- 评测结果具有可复现性。

该修改需要重新入库已有 collection，否则旧 point 的 sparse index 仍然是旧 hash 生成的。

### 阶段三：扩大候选并接入 rerank

当前 hybrid 最终直接返回 `top_k`。建议在评测和检索 API 中区分：

- `candidate_k`：召回和融合阶段保留多少候选，例如 30 或 50。
- `top_k`：最终返回多少结果，例如 10。
- `rerank_enabled`：是否对候选做精排。

推荐实验路径：

```text
dense top50 + sparse top50
→ hybrid fuse top30
→ rerank top30
→ final top10
```

预期收益：

- 如果相关 chunk 已经在 top30/top50，但没进 top10，rerank 会提升 `MRR` 和 `Recall@5`。
- 不需要修改知识库内容。
- 能更真实地模拟生产 RAG：召回负责“捞得全”，rerank 负责“排得准”。

### 阶段四：chunk 结构优化

ITSM 问句常问“是否升级”“能否直接处理”“重置前确认什么”“先修还是先评估”。这类问题依赖流程条件和约束，如果 chunk 切分不合理，语义会断裂。

建议检查并优化：

- 标题和正文不要被切散。
- 流程步骤尽量保留在同一 chunk 或相邻 chunk。
- 表格行保持完整。
- 保留 `parent_doc_id` 或 `parent_chunk_id`，支持父子 chunk 检索。
- 小 chunk 用于召回，大 chunk 用于回答。

父子 chunk 的目标不是堆词，而是修复“召回粒度”和“回答上下文粒度”之间的矛盾。

进一步建议引入 small-to-big / sentence window 机制：

```text
检索阶段：使用小 chunk、句子或结构块，提高定位精度。
上下文阶段：根据 logic_idx / prev_view_id / next_view_id 取邻近窗口。
回答阶段：把窗口后的上下文交给主系统 LLM，而不是只给孤立命中句。
```

该机制要求每个 chunk 在 payload 中保留稳定的顺序和邻居信息。项目已经有 `logic_idx` 和 prev/next 相关字段，适合在此基础上扩展。

### 阶段五：query intent routing

对 query 做轻量分析，用于选择检索策略，而不是改写知识库。

可识别信号：

- 是否包含英文缩写、状态码、错误码：`API Key`、`DNS`、`HTTPS`、`CVE`、`MFA`、`429`、`5xx`。
- 是否是流程判断题：`应该升级吗`、`可以吗`、`是否需要`、`先...还是...`。
- 是否是排查题：`怎么排查`、`检查什么`、`收集哪些信息`。
- 是否是安全合规题：`泄露`、`删除`、`密码`、`敏感`、`公网`。

策略示例：

```text
关键词/错误码强相关问题：提高 sparse 权重。
流程判断题：扩大 candidate_k，并启用 rerank。
安全合规题：rerank 时更重视“禁止、必须、升级、审批、确认”等语义。
普通概念问答：保持默认 hybrid 权重。
```

这类 routing 属于检索策略，不污染知识库正文。

可选增强：对复杂 query 启用 query rewriting 或 HyDE。生成内容只参与当前请求检索，并写入评测诊断：

```json
{
  "query_rewrite": {
    "enabled": true,
    "strategy": "hyde",
    "original_query": "...",
    "effective_query": "...",
    "warning": null
  }
}
```

如果 rewrite 后命中提升，需要同时记录代价和失败样例，避免把不可控生成逻辑变成新的黑箱。

### 阶段六：置信度校准和拒答机制

系统不应该只追求命中率，还要知道何时不该答。

建议为 `/retrieve` 或上层 RAG 调用返回置信度信号：

- `top1_score` 是否低于阈值。
- `top1 - top2` 分差是否过小。
- dense 和 sparse 是否互相支持同一 doc。
- rerank 分数是否低。
- topK 是否来自多个互相矛盾的文档。

低置信度时返回：

```json
{
  "confidence": "low",
  "action": "ask_clarification_or_escalate",
  "reason": "no_reliable_evidence"
}
```

这能覆盖类似“RAG 没有命中任何知识库文档，AI 应该怎么处理？”的问题，也能减少错误强答。

## 实验计划

每次只改变一个变量，记录指标变化。

建议 baseline：

```text
mode=hybrid
top_k=10
candidate_k=20
rerank=false
score_threshold=0.3
vector_weight=0.7
sparse_weight=0.3
```

建议实验组：

| 实验 | 变量 | 观察指标 |
| --- | --- | --- |
| E1 | stable sparse hash + 重新入库 | Recall@10、Hit Rate |
| E2 | candidate_k 20 → 50 | Recall@10、未命中分类 |
| E3 | candidate_k 50 + rerank top30→top10 | MRR、Recall@5、NDCG@10 |
| E4 | score_threshold 0.3 → 0.2 → 0.1 → 0 | Recall@10、Precision@10 |
| E5 | 动态 hybrid 权重 | Hit Rate、MRR |
| E6 | chunk 结构调整 | Recall@10、人工抽样质量 |
| E7 | low confidence 阈值 | 错误强答率、拒答准确性 |
| E8 | small-to-big / sentence window | MRR、答案上下文完整性 |
| E9 | HyDE / query rewrite | Recall@10、延迟、失败样例 |
| E10 | RRF vs MinMax 融合 | Recall@10、MRR、稳定性 |

## 派生索引边界

外部实践中常见的 sample questions、摘要、query rewrite、HyDE 文本、聚类摘要都可能提升召回，但这些内容不能混入原始知识库。

建议把内容分成三层：

| 层级 | 内容 | 是否可人工编辑 | 是否作为事实来源 |
| --- | --- | --- | --- |
| Source layer | 原始文档、流程、制度、工单知识正文 | 是 | 是 |
| Derived retrieval layer | 摘要、样例问题、窗口索引、父子 chunk 映射、向量、sparse index | 否，自动生成 | 否 |
| Runtime query layer | query rewrite、HyDE、query routing、临时 subquery | 否，请求时生成 | 否 |

约束：

- 所有派生内容必须能从 source layer 重新生成。
- 所有派生内容必须带 provenance，能追溯到原始 `doc_id#chunk_index`。
- 评测报告需要区分“原文命中”和“派生层命中”。
- 回答引用只能指向 source layer，不能引用 HyDE 或样例问题作为事实。

## 验收标准

最低验收：

- 评测报告能输出每个未命中样本的失败阶段。
- sparse hash 修改后评测结果在服务重启前后保持一致。
- 不向知识库原文追加投机性关键词。

质量验收：

- `Hit Rate` 相对 baseline 有明确提升。
- `Recall@10` 提升，同时 `Precision@10` 不出现不可接受下降。
- `MRR` 提升，说明正确结果更靠前。
- 未命中样本可以被归因到明确阶段，而不是只有一串红色列表。
- 派生索引提升命中时，能追溯到真实 source chunk。

工程验收：

- 相关修改有单元测试或评测用例覆盖。
- 评测报告可通过 UI 查看。
- 文档说明需要重新入库的场景，尤其是 sparse hash 变更。
- 派生索引可以单独重建和关闭。

## 推荐实施顺序

1. 增强评测诊断，先看失败分布。
2. 修复 sparse 稳定 hash，并重新入库测试 collection。
3. 暴露 `candidate_k`，记录 topN 分层命中情况。
4. 接入 rerank 实验路径。
5. 做 chunk 结构和父子 chunk 优化。
6. 加 query intent routing。
7. 做置信度校准和低置信度响应。
8. 在诊断数据支持下，再考虑 sentence window、HyDE 或 RAPTOR 摘要索引。

## 面试和答辩表述

可以这样概括：

> 这个项目不会通过给知识库堆关键词来提高评测分数。我的优化思路是先做 failure analysis，把未命中拆成 dense 召回失败、sparse 召回失败、融合排序失败、chunk 结构问题和入库或标注问题。然后优先修复 sparse hash 这种确定性问题，扩大候选集并用 reranker 精排，优化 chunk 结构和父子检索；必要时引入 sentence window、query rewrite、HyDE 或摘要索引，但都作为可重建的派生检索层，不写回原始知识库。最后加入 query intent routing 和置信度校准。知识库保持事实干净，检索层负责理解、召回、排序和拒答。
