"""契约测试：定义主系统 RAG Client 期望的响应 schema，断言 quillrag 实际响应一致。

为下一个 change `switch-main-system-to-rag-client` 预留。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

EXPECTED_API_RESPONSE_KEYS = {"code", "message", "data"}
EXPECTED_RETRIEVE_RESULT_KEYS = {"content", "score", "doc_id", "chunk_index", "metadata"}
EXPECTED_CHUNK_METADATA_KEYS = {"source", "page", "category", "heading_path", "doc_id", "chunk_index"}
EXPECTED_HEALTH_KEYS = {"status", "components"}


def _assert_keys(actual: dict, expected: set[str], *, allow_extra: bool = True) -> None:
    missing = expected - set(actual.keys())
    assert not missing, f"missing keys: {missing}, actual={list(actual.keys())}"
    if not allow_extra:
        extra = set(actual.keys()) - expected
        assert not extra, f"unexpected extra keys: {extra}"


def test_parse_response_schema(rag_service_client, sample_text) -> None:
    response = rag_service_client.post(
        "/parse", data={"text": sample_text, "strategy": "fixed"}
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    _assert_keys(body, EXPECTED_API_RESPONSE_KEYS, allow_extra=True)
    assert body["code"] in {"OK", "FAILED"}
    assert isinstance(body["message"], str)
    assert isinstance(body["data"], dict)
    _assert_keys(body["data"], {"doc_id", "chunks", "layout_summary"})
    assert isinstance(body["data"]["chunks"], list)
    if body["data"]["chunks"]:
        first = body["data"]["chunks"][0]
        assert "content" in first
        assert "metadata" in first
        _assert_keys(first["metadata"], EXPECTED_CHUNK_METADATA_KEYS, allow_extra=True)


def test_retrieve_response_schema(rag_service_client, mocked_qdrant, mocked_embedder) -> None:
    from app.retrieval import dense_searcher, sparse_searcher

    with patch.object(dense_searcher, "search", lambda **kw: []), \
         patch.object(sparse_searcher, "search", lambda **kw: []):
        response = rag_service_client.post(
            "/retrieve",
            json={"query": "q", "collection": "c1", "mode": "hybrid"},
        )
    assert response.status_code == 200
    body = response.json()
    _assert_keys(body, EXPECTED_API_RESPONSE_KEYS, allow_extra=True)
    _assert_keys(body["data"], {"results", "actual_mode"})
    assert body["data"]["actual_mode"] in {"vector", "bm25", "hybrid"}


def test_rerank_response_schema(rag_service_client, mocked_reranker) -> None:
    response = rag_service_client.post(
        "/rerank", json={"query": "q", "documents": ["a", "b"], "top_k": 2}
    )
    assert response.status_code == 200
    body = response.json()
    _assert_keys(body, EXPECTED_API_RESPONSE_KEYS, allow_extra=True)
    _assert_keys(body["data"], {"results"})
    for item in body["data"]["results"]:
        _assert_keys(item, {"content", "score", "original_index"}, allow_extra=True)


def test_health_response_schema(rag_service_client) -> None:
    response = rag_service_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    _assert_keys(body, EXPECTED_HEALTH_KEYS, allow_extra=True)
    assert body["status"] in {"ok", "degraded"}
    assert {"qdrant", "embedder", "reranker"} <= set(body["components"].keys())


def test_error_response_shape(rag_service_client) -> None:
    response = rag_service_client.post("/parse", data={})
    body = response.json()
    _assert_keys(body, {"code", "message", "error_code"}, allow_extra=True)
    assert body["code"] == "FAILED"
    assert body["error_code"]
