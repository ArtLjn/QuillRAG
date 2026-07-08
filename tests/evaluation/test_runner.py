"""检索评测 runner 单测。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.evaluation.runner import (
    EvaluationSample,
    load_golden_set,
    make_result_key,
    make_result_keys,
    run_retrieval_evaluation,
)
from app.models.chunk import ChunkMetadata
from app.models.query import RetrieveMode, RetrieveResult


def test_load_golden_set_reads_jsonl(tmp_path: Path) -> None:
    golden = tmp_path / "retrieval.jsonl"
    golden.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "query": "登录失败怎么排查？",
                        "collection": "ticket_knowledge",
                        "relevant": ["login-doc#0"],
                        "tags": ["technical", "login"],
                    },
                    ensure_ascii=False,
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    samples = load_golden_set(golden)

    assert samples == [
        EvaluationSample(
            query="登录失败怎么排查？",
            collection="ticket_knowledge",
            relevant={"login-doc#0"},
            tags=["technical", "login"],
        )
    ]


def test_make_result_key_prefers_doc_id_and_chunk_index() -> None:
    result = RetrieveResult(content="命中内容", score=0.91, doc_id="doc-a", chunk_index=3)

    assert make_result_key(result) == "doc-a#3"


def test_make_result_keys_includes_source_and_source_stem() -> None:
    result = RetrieveResult(
        content="账号锁定处理",
        score=0.91,
        doc_id="doc-a",
        chunk_index=3,
        metadata=ChunkMetadata(source="itsm-login-account.md"),
    )

    assert make_result_keys(result) == {
        "doc-a#3",
        "itsm-login-account.md#3",
        "itsm-login-account#3",
    }


@pytest.mark.asyncio
async def test_run_retrieval_evaluation_computes_metrics(tmp_path: Path) -> None:
    golden = tmp_path / "retrieval.jsonl"
    report_dir = tmp_path / "reports"
    golden.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "query": "登录失败",
                        "collection": "ticket_knowledge",
                        "relevant": ["login-doc#0"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "query": "退款到账",
                        "collection": "ticket_knowledge",
                        "relevant": ["refund-doc#1"],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    async def fake_retrieve(**kwargs):
        if kwargs["query"] == "登录失败":
            return [
                RetrieveResult(content="登录失败排查", score=0.9, doc_id="login-doc", chunk_index=0),
                RetrieveResult(content="其他内容", score=0.2, doc_id="other-doc", chunk_index=0),
            ], None, RetrieveMode.HYBRID
        return [
            RetrieveResult(content="其他内容", score=0.8, doc_id="other-doc", chunk_index=0),
            RetrieveResult(content="退款到账说明", score=0.7, doc_id="refund-doc", chunk_index=1),
        ], None, RetrieveMode.HYBRID

    with patch("app.evaluation.runner.retrieve", new=AsyncMock(side_effect=fake_retrieve)):
        report = await run_retrieval_evaluation(
            dataset_path=golden,
            report_dir=report_dir,
            mode=RetrieveMode.HYBRID,
            top_k=3,
            k_values=[1, 3],
        )

    assert report["summary"]["sample_count"] == 2
    assert report["summary"]["metrics"]["recall_at_k"]["1"] == 0.5
    assert report["summary"]["metrics"]["recall_at_k"]["3"] == 1.0
    assert report["summary"]["metrics"]["mrr"] == 0.75
    assert report["samples"][0]["first_hit_rank"] == 1
    assert report["samples"][1]["first_hit_rank"] == 2
    assert Path(report["report_path"]).exists()


@pytest.mark.asyncio
async def test_run_retrieval_evaluation_matches_source_stem_alias(tmp_path: Path) -> None:
    golden = tmp_path / "retrieval.jsonl"
    report_dir = tmp_path / "reports"
    golden.write_text(
        json.dumps(
            {
                "query": "账号锁定",
                "collection": "ticket_knowledge",
                "relevant": ["itsm-login-account#0"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def fake_retrieve(**kwargs):
        return [
            RetrieveResult(
                content="账号锁定处理",
                score=0.9,
                doc_id="real-doc-id",
                chunk_index=0,
                metadata=ChunkMetadata(source="itsm-login-account.md"),
            ),
        ], None, RetrieveMode.HYBRID

    with patch("app.evaluation.runner.retrieve", new=AsyncMock(side_effect=fake_retrieve)):
        report = await run_retrieval_evaluation(
            dataset_path=golden,
            report_dir=report_dir,
            mode=RetrieveMode.HYBRID,
            top_k=3,
            k_values=[1],
        )

    assert report["summary"]["metrics"]["recall_at_k"]["1"] == 1.0
    assert report["summary"]["metrics"]["hit_rate"] == 1.0
    assert report["samples"][0]["first_hit_rank"] == 1
