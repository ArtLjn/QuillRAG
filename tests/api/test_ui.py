"""UI 页面单测。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_root_redirects_to_ui(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {301, 302, 307}
    assert response.headers["location"] == "/ui/"


def test_index_page_renders_collections(client: TestClient) -> None:
    with patch("app.ui.router.collection_service.list_all") as mock_list:
        mock_list.return_value = [{"name": "ticket_knowledge", "points_count": 12, "status": "green"}]
        response = client.get("/ui/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ticket_knowledge" in response.text
    assert "Collections" in response.text


def test_index_page_shows_empty_hint(client: TestClient) -> None:
    with patch("app.ui.router.collection_service.list_all", return_value=[]):
        response = client.get("/ui/")
    assert response.status_code == 200
    assert "还没有 collection" in response.text


def test_collection_detail_lists_documents(client: TestClient) -> None:
    payload = {
        "total": 1,
        "page": 1,
        "page_size": 20,
        "documents": [
            {
                "doc_id": "abc123",
                "collection": "ticket_knowledge",
                "source": "demo.md",
                "category": "technical",
                "chunk_count": 6,
                "content_hash": "deadbeef",
                "extra": {},
                "ingested_at": "2026-07-02T10:00:00",
            }
        ],
    }
    with patch("app.ui.router.collection_service.list_documents", return_value=payload):
        response = client.get("/ui/collections/ticket_knowledge")
    assert response.status_code == 200
    assert "abc123" in response.text
    assert "demo.md" in response.text


def test_retrieve_debug_page_renders(client: TestClient) -> None:
    with patch("app.ui.router.collection_service.list_all") as mock_list:
        mock_list.return_value = [{"name": "ticket_knowledge", "points_count": 1, "status": "green"}]
        response = client.get("/ui/retrieve")
    assert response.status_code == 200
    assert "检索调试器" in response.text
    assert "ticket_knowledge" in response.text


def test_retrieve_debug_prefers_ticket_knowledge_first(client: TestClient) -> None:
    with patch("app.ui.router.collection_service.list_all") as mock_list:
        mock_list.return_value = [
            {"name": "knowledge_base", "points_count": 1, "status": "green"},
            {"name": "ticket_knowledge", "points_count": 1, "status": "green"},
        ]
        response = client.get("/ui/retrieve")

    assert response.status_code == 200
    assert response.text.find('value="ticket_knowledge"') < response.text.find('value="knowledge_base"')


def test_health_page_renders(client: TestClient) -> None:
    with patch("app.ui.router.check_health") as mock_health:
        from app.core.response import HealthResponse

        mock_health.return_value = HealthResponse(
            status="ok",
            components={"qdrant": "ok", "embedder": "ok", "reranker": "loading"},
        )
        response = client.get("/ui/health")
    assert response.status_code == 200
    assert "ok" in response.text
    assert "qdrant" in response.text


def test_health_page_renders_idle_as_non_error_state(client: TestClient) -> None:
    with patch("app.ui.router.check_health") as mock_health:
        from app.core.response import HealthResponse

        mock_health.return_value = HealthResponse(
            status="ok",
            components={"qdrant": "ok", "embedder": "ok", "reranker": "idle"},
        )
        response = client.get("/ui/health")

    assert response.status_code == 200
    assert "idle" in response.text
    assert "懒加载未触发" in response.text
    assert "bg-red-100 text-red-700\">idle" not in response.text


def test_evaluation_page_shows_failure_diagnostics(client: TestClient) -> None:
    report = {
        "summary": {
            "sample_count": 1,
            "metrics": {
                "recall_at_k": {"1": 0.0, "5": 0.0},
                "precision_at_k": {"1": 0.0, "5": 0.0},
                "ndcg_at_k": {"1": 0.0, "5": 0.0},
                "mrr": 0.0,
                "hit_rate": 0.0,
            },
        },
        "mode": "hybrid",
        "top_k": 1,
        "diagnostic_k": 3,
        "k_values": [1, 5],
        "started_at": "2026-07-10T00:00:00+00:00",
        "finished_at": "2026-07-10T00:00:01+00:00",
        "dataset_path": "fixtures/evaluation/retrieval_itsm_seed.jsonl",
        "report_path": "data/evaluation/reports/retrieval_eval.json",
        "samples": [
            {
                "query": "HTTPS 证书过期导致登录页面打不开，应该更新哪里？",
                "relevant": ["itsm-tls-certificate#0"],
                "retrieved": ["itsm-login-account#0"],
                "hit": False,
                "diagnostics": {
                    "dense_top3_hit": True,
                    "sparse_top3_hit": False,
                    "hybrid_top3_hit": True,
                    "final_top1_hit": False,
                    "failure_stage": "ranking",
                },
            }
        ],
    }
    with patch("app.ui.router.load_latest_report", return_value=report):
        response = client.get("/ui/evaluation")

    assert response.status_code == 200
    assert "failure_stage" in response.text
    assert "ranking" in response.text
    assert "dense_top3_hit" in response.text


def test_document_chunks_sorts_by_logic_idx(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.ui import router as ui_router

    fake_points = [
        SimpleNamespace(id="a", payload={"content": "段 B", "category": "paragraph", "page": 1, "chunk_index": 1, "logic_idx": 5}),
        SimpleNamespace(id="b", payload={"content": "段 A", "category": "paragraph", "page": 1, "chunk_index": 0, "logic_idx": 2}),
    ]
    fake_client = MagicMock()
    fake_client.scroll.return_value = (fake_points, None)

    monkeypatch.setattr(ui_router, "ensure_collection_or_raise", lambda name: None)
    monkeypatch.setattr(ui_router, "get_client", lambda: fake_client)

    response = client.get("/ui/collections/c1/documents/abc")
    assert response.status_code == 200, response.text
    pos_a = response.text.find("段 A")
    pos_b = response.text.find("段 B")
    assert 0 < pos_a < pos_b
