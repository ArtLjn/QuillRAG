"""评测 API 测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_latest_evaluation_returns_empty_when_no_report(client: TestClient) -> None:
    with patch("app.api.evaluation.load_latest_report", return_value=None):
        response = client.get("/evaluation/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK"
    assert body["data"]["available"] is False
    assert body["data"]["report"] is None


def test_latest_evaluation_returns_report(client: TestClient) -> None:
    report = {
        "summary": {
            "sample_count": 2,
            "metrics": {"recall_at_k": {"5": 1.0}, "mrr": 0.75},
        }
    }
    with patch("app.api.evaluation.load_latest_report", return_value=report):
        response = client.get("/evaluation/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["available"] is True
    assert body["data"]["report"] == report


def test_run_evaluation_returns_report(client: TestClient) -> None:
    report = {
        "schema_version": "retrieval-eval-v1",
        "summary": {"sample_count": 1, "metrics": {"recall_at_k": {"5": 1.0}}},
    }
    with patch("app.api.evaluation.run_retrieval_evaluation", new=AsyncMock(return_value=report)) as mock_run:
        response = client.post(
            "/evaluation/run",
            json={
                "dataset_path": "data/evaluation/golden/retrieval.jsonl",
                "mode": "hybrid",
                "top_k": 10,
                "k_values": [1, 5, 10],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK"
    assert body["data"] == report
    mock_run.assert_awaited_once()
