# RAG 检索评测标准

QuillRAG 的基础评测采用确定性 golden set，不依赖 LLM judge。核心目标是回答：

- 检索器是否把正确 chunk 召回到 top-k。
- hybrid / vector / bm25 三种模式谁更稳定。
- chunk、Embedding、融合权重调整后，召回指标是否退化。

## Golden Set 格式

评测集使用 JSONL，一行一个查询样本：

```json
{"query":"API 报错应该如何排查？","collection":"ticket_knowledge","relevant":["51f020678a07#0"],"tags":["technical","api"]}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `query` | 是 | 用户查询或工单问题 |
| `collection` | 是 | 检索目标 collection |
| `relevant` | 是 | 相关 chunk key 列表，格式为 `doc_id#chunk_index` |
| `tags` | 否 | 场景标签，如 `technical`、`billing`、`api` |
| `filters` | 否 | 透传给 `/retrieve` 的 metadata filter |
| `use_hyde` | 否 | 是否启用 HyDE |

示例文件：`fixtures/evaluation/retrieval.example.jsonl`。

正式评测建议复制为：

```bash
mkdir -p data/evaluation/golden
cp fixtures/evaluation/retrieval.example.jsonl data/evaluation/golden/retrieval.jsonl
```

然后按真实文档和 chunk 标注 `relevant`。

## 指标口径

| 指标 | 说明 |
| --- | --- |
| `recall@k` | top-k 结果命中的相关 chunk 数 / 相关 chunk 总数 |
| `precision@k` | top-k 结果中相关 chunk 占比 |
| `MRR` | 第一个相关结果排名的倒数 |
| `NDCG@k` | 带位置折扣的排序质量 |
| `hit_rate` | 至少命中一个相关 chunk 的样本比例 |

报告中的 `recall@k` 可对应 Ragas 的 `context_recall` 基础口径；`precision@k` 可对应 `context_precision` 的确定性版本。Ragas、DeepEval、TruLens 可作为后续 LLM-as-judge 增强层，用于评估生成答案的 faithfulness / answer relevancy；基础检索评测仍以 golden set 为准。

## 运行评测

```bash
source .venv/bin/activate
python scripts/eval_retrieval.py \
  --dataset data/evaluation/golden/retrieval.jsonl \
  --mode hybrid \
  --top-k 10 \
  --k 1 3 5 10
```

输出示例：

```text
report_path=data/evaluation/reports/retrieval_eval_20260706_103000.json
sample_count=20
hit_rate=0.9000
mrr=0.7800
recall@1=0.5500
recall@3=0.7500
recall@5=0.8500
recall@10=0.9000
```

报告会写入 `data/evaluation/reports/`。

## API

读取最新报告：

```bash
curl http://localhost:8001/evaluation/latest
```

触发评测：

```bash
curl -X POST http://localhost:8001/evaluation/run \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_path": "data/evaluation/golden/retrieval.jsonl",
    "mode": "hybrid",
    "top_k": 10,
    "k_values": [1, 3, 5, 10]
  }'
```

生产环境开启鉴权时，需要带 `X-API-Key`。

## 标注建议

1. 先从业务高频问题选 20-50 条 query。
2. 每条 query 标 1-3 个相关 chunk。
3. 覆盖技术、计费、投诉、咨询四类工单。
4. 每次调整 chunk 策略、Embedding 模型、融合权重后跑同一份 golden set。
5. 论文中报告 `recall@5`、`MRR`、`NDCG@10`，并补充失败样本分析。
