#!/usr/bin/env python3
"""运行 RAG 检索评测并输出 JSON 报告路径。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.runner import (  # noqa: E402
    DEFAULT_GOLDEN_PATH,
    DEFAULT_K_VALUES,
    DEFAULT_REPORT_DIR,
    run_retrieval_evaluation,
)
from app.models.query import RetrieveMode  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QuillRAG retrieval evaluation")
    parser.add_argument("--dataset", default=str(DEFAULT_GOLDEN_PATH), help="Golden set JSONL path")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for JSON reports")
    parser.add_argument("--mode", choices=[m.value for m in RetrieveMode], default=RetrieveMode.HYBRID.value)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--k", type=int, nargs="+", default=DEFAULT_K_VALUES)
    parser.add_argument("--print-json", action="store_true", help="Print full report JSON")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    report = await run_retrieval_evaluation(
        dataset_path=Path(args.dataset),
        report_dir=Path(args.report_dir),
        mode=RetrieveMode(args.mode),
        top_k=args.top_k,
        k_values=args.k,
    )
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    summary = report["summary"]["metrics"]
    recall = summary.get("recall_at_k", {})
    print(f"report_path={report['report_path']}")
    print(f"sample_count={report['summary']['sample_count']}")
    print(f"hit_rate={summary.get('hit_rate', 0.0):.4f}")
    print(f"mrr={summary.get('mrr', 0.0):.4f}")
    for k, value in recall.items():
        print(f"recall@{k}={value:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
