"""/collections CRUD API 测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_create_collection(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.create") as mock_create:
        mock_create.return_value = {"collection": "c1", "action": "created", "vector_dim": 1024}
        response = client.post("/collections", json={"name": "c1", "vector_dim": 1024})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["collection"] == "c1"
    assert body["data"]["vector_dim"] == 1024


def test_list_collections(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.list_all") as mock_list:
        mock_list.return_value = [{"name": "c1", "points_count": 100}]
        response = client.get("/collections")
    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["name"] == "c1"


def test_delete_collection(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.remove") as mock_remove:
        mock_remove.return_value = {"collection": "c1", "action": "deleted", "deleted_documents": 3}
        response = client.delete("/collections/c1")
    assert response.status_code == 200
    assert response.json()["data"]["deleted_documents"] == 3


def test_list_documents_pagination(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.list_documents") as mock_list:
        mock_list.return_value = {
            "total": 5,
            "page": 1,
            "page_size": 10,
            "documents": [{"doc_id": "d1"}],
        }
        response = client.get("/collections/c1/documents?page=1&page_size=10")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total"] == 5


def test_delete_document(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.delete_document") as mock_delete:
        mock_delete.return_value = {
            "doc_id": "d1",
            "collection": "c1",
            "metadata_removed": True,
            "points_removed": 5,
        }
        response = client.delete("/collections/c1/documents/d1")
    assert response.status_code == 200
    assert response.json()["data"]["points_removed"] == 5


def test_prune_orphan_points(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.prune_orphan_points") as mock_prune:
        mock_prune.return_value = {
            "collection": "c1",
            "dry_run": False,
            "orphan_doc_ids": ["old"],
            "orphan_point_count": 3,
            "points_removed": 3,
        }
        response = client.post("/collections/c1/prune-orphans")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["points_removed"] == 3
    mock_prune.assert_called_once_with("c1", dry_run=False)


def test_prune_orphan_points_dry_run(client: TestClient) -> None:
    with patch("app.api.collections.collection_service.prune_orphan_points") as mock_prune:
        mock_prune.return_value = {
            "collection": "c1",
            "dry_run": True,
            "orphan_doc_ids": ["old"],
            "orphan_point_count": 3,
            "points_removed": 0,
        }
        response = client.post("/collections/c1/prune-orphans?dry_run=true")

    assert response.status_code == 200
    mock_prune.assert_called_once_with("c1", dry_run=True)
