"""RAG 检索评测 API。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.response import ApiResponse
from app.evaluation.runner import (
    DEFAULT_DIAGNOSTIC_K,
    DEFAULT_GOLDEN_PATH,
    DEFAULT_K_VALUES,
    DEFAULT_REPORT_DIR,
    load_latest_report,
    run_retrieval_evaluation,
)
from app.models.query import RetrieveMode

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


class EvaluationRunBody(BaseModel):
    dataset_path: str = Field(default=str(DEFAULT_GOLDEN_PATH))
    report_dir: str = Field(default=str(DEFAULT_REPORT_DIR))
    mode: RetrieveMode = RetrieveMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=100)
    diagnostic_k: int = Field(default=DEFAULT_DIAGNOSTIC_K, ge=1, le=200)
    k_values: list[int] = Field(default_factory=lambda: DEFAULT_K_VALUES.copy())


@router.get("/latest")
async def latest_evaluation() -> ApiResponse[dict[str, Any]]:
    report = load_latest_report()
    return ApiResponse.ok({"available": report is not None, "report": report})


@router.post("/run")
async def run_evaluation(body: EvaluationRunBody) -> ApiResponse[dict[str, Any]]:
    report = await run_retrieval_evaluation(
        dataset_path=Path(body.dataset_path),
        report_dir=Path(body.report_dir),
        mode=body.mode,
        top_k=body.top_k,
        diagnostic_k=body.diagnostic_k,
        k_values=body.k_values,
    )
    return ApiResponse.ok(report)
