"""检索评测 runner：读取 golden set，调用 /retrieve 逻辑并生成报告。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.metrics import compute_retrieval_metrics
from app.models.query import RetrieveMode, RetrieveResult
from app.services.retrieve_service import retrieve

DEFAULT_GOLDEN_PATH = Path("fixtures/evaluation/retrieval_itsm_seed.jsonl")
DEFAULT_REPORT_DIR = Path("data/evaluation/reports")
DEFAULT_K_VALUES = [1, 3, 5, 10]


@dataclass
class EvaluationSample:
    query: str
    collection: str
    relevant: set[str]
    tags: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    use_hyde: bool = False


def load_golden_set(path: Path | str) -> list[EvaluationSample]:
    """读取 JSONL golden set。

    每行字段：
    - query: 查询文本
    - collection: 目标 collection
    - relevant: 相关 chunk key 列表，格式为 doc_id#chunk_index
    - tags / filters / use_hyde: 可选
    """
    dataset_path = Path(path)
    samples: list[EvaluationSample] = []

    with dataset_path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            payload = json.loads(line)
            relevant = set(payload.get("relevant") or [])
            if not payload.get("query") or not payload.get("collection") or not relevant:
                raise ValueError(f"invalid golden sample at {dataset_path}:{line_no}")
            samples.append(
                EvaluationSample(
                    query=payload["query"],
                    collection=payload["collection"],
                    relevant=relevant,
                    tags=list(payload.get("tags") or []),
                    filters=dict(payload.get("filters") or {}),
                    use_hyde=bool(payload.get("use_hyde", False)),
                )
            )

    return samples


def make_result_key(result: RetrieveResult) -> str:
    """把检索结果映射为 golden set 对齐 key。"""
    doc_id = result.doc_id or result.metadata.doc_id
    return f"{doc_id}#{result.chunk_index}"


def make_result_keys(result: RetrieveResult) -> set[str]:
    """生成可用于评测匹配的一组 key。

    正式评测建议使用真实 `doc_id#chunk_index`。为了让人工维护 golden set 更轻量，
    这里也兼容 `source#chunk_index` 和 `source_stem#chunk_index`。
    """
    chunk_index = result.chunk_index
    keys = {make_result_key(result)}
    source = result.metadata.source
    if source:
        keys.add(f"{source}#{chunk_index}")
        keys.add(f"{Path(source).stem}#{chunk_index}")
    return keys


async def run_retrieval_evaluation(
    *,
    dataset_path: Path | str = DEFAULT_GOLDEN_PATH,
    report_dir: Path | str = DEFAULT_REPORT_DIR,
    mode: RetrieveMode | str = RetrieveMode.HYBRID,
    top_k: int = 10,
    k_values: list[int] | None = None,
) -> dict[str, Any]:
    """运行检索评测并写入 JSON 报告。"""
    actual_mode = RetrieveMode(mode)
    ks = k_values or DEFAULT_K_VALUES
    samples = load_golden_set(dataset_path)
    evaluated_samples: list[dict[str, Any]] = []
    metric_inputs: list[tuple[list[str], set[str]]] = []

    started_at = datetime.now(UTC)
    for sample in samples:
        results, warning, result_mode = await retrieve(
            query=sample.query,
            collection=sample.collection,
            mode=actual_mode,
            top_k=top_k,
            filters=sample.filters or None,
            use_hyde=sample.use_hyde,
        )
        retrieved_keys = [make_result_key(result) for result in results]
        retrieved_aliases = [make_result_keys(result) for result in results]
        metric_inputs.append((retrieved_keys, sample.relevant))
        alias_metric_inputs = _alias_metric_inputs(retrieved_keys, retrieved_aliases, sample.relevant)
        metric_inputs[-1] = alias_metric_inputs
        first_hit_rank = _first_hit_rank_by_alias(retrieved_aliases, sample.relevant)
        evaluated_samples.append(
            {
                "query": sample.query,
                "collection": sample.collection,
                "tags": sample.tags,
                "relevant": sorted(sample.relevant),
                "retrieved": retrieved_keys,
                "retrieved_aliases": [sorted(keys) for keys in retrieved_aliases],
                "first_hit_rank": first_hit_rank,
                "hit": first_hit_rank is not None,
                "actual_mode": result_mode.value,
                "warning": warning,
            }
        )

    metrics = compute_retrieval_metrics(metric_inputs, k_values=ks)
    finished_at = datetime.now(UTC)
    report = {
        "schema_version": "retrieval-eval-v1",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "dataset_path": str(dataset_path),
        "mode": actual_mode.value,
        "top_k": top_k,
        "k_values": ks,
        "summary": {
            "sample_count": metrics.sample_count,
            "metrics": _stringify_metric_keys(metrics.to_dict()),
        },
        "samples": evaluated_samples,
    }
    report_path = _write_report(report, Path(report_dir), finished_at)
    report["report_path"] = str(report_path)
    return report


def load_latest_report(report_dir: Path | str = DEFAULT_REPORT_DIR) -> dict[str, Any] | None:
    """读取最新评测报告；没有报告时返回 None。"""
    reports = sorted(Path(report_dir).glob("retrieval_eval_*.json"))
    if not reports:
        return None
    with reports[-1].open("r", encoding="utf-8") as f:
        return json.load(f)


def _first_hit_rank(retrieved: list[str], relevant: set[str]) -> int | None:
    for index, key in enumerate(retrieved, start=1):
        if key in relevant:
            return index
    return None


def _first_hit_rank_by_alias(retrieved_aliases: list[set[str]], relevant: set[str]) -> int | None:
    for index, keys in enumerate(retrieved_aliases, start=1):
        if keys & relevant:
            return index
    return None


def _alias_metric_inputs(
    retrieved_keys: list[str],
    retrieved_aliases: list[set[str]],
    relevant: set[str],
) -> tuple[list[str], set[str]]:
    matched_keys: list[str] = []
    for key, aliases in zip(retrieved_keys, retrieved_aliases, strict=True):
        matched = sorted(aliases & relevant)
        matched_keys.append(matched[0] if matched else key)
    return matched_keys, relevant


def _stringify_metric_keys(metrics: dict[str, Any]) -> dict[str, Any]:
    converted = dict(metrics)
    for key in ("recall_at_k", "precision_at_k", "ndcg_at_k"):
        converted[key] = {str(k): v for k, v in converted.get(key, {}).items()}
    return converted


def _write_report(report: dict[str, Any], report_dir: Path, finished_at: datetime) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"retrieval_eval_{finished_at.strftime('%Y%m%d_%H%M%S')}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path


__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_K_VALUES",
    "DEFAULT_REPORT_DIR",
    "EvaluationSample",
    "load_golden_set",
    "load_latest_report",
    "make_result_key",
    "make_result_keys",
    "run_retrieval_evaluation",
]
