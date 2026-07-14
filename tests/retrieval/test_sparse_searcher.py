"""sparse_searcher 单测：mock QdrantClient，验证 BM25 输入构造。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from app.retrieval import sparse_searcher


def test_tokenize_drops_empty() -> None:
    tokens = sparse_searcher.tokenize("你好  世界 ")
    assert "你好" in tokens
    assert "世界" in tokens


def test_build_sparse_vector_returns_indices_and_values() -> None:
    sv = sparse_searcher.build_sparse_vector("错误码 错误码 处理")
    assert isinstance(sv["indices"], list)
    assert isinstance(sv["values"], list)
    assert len(sv["indices"]) == len(sv["values"])
    assert all(v >= 1.0 for v in sv["values"])


def test_hash_index_is_stable_md5_derived() -> None:
    token = "API Key"
    digest = hashlib.md5(token.encode("utf-8")).digest()
    expected = int.from_bytes(digest[:4], "big") % (2**31)

    assert sparse_searcher._hash_index(token) == expected


def test_build_sparse_vector_handles_empty_string() -> None:
    sv = sparse_searcher.build_sparse_vector("")
    assert sv == {"indices": [], "values": []}


def test_search_returns_results_from_payload() -> None:
    fake_hit = SimpleNamespace(
        id="doc1_0",
        score=8.5,
        payload={
            "content": "结果内容",
            "doc_id": "doc1",
            "chunk_index": 0,
            "category": "paragraph",
            "heading_path": [],
        },
    )
    fake_client = SimpleNamespace(
        query_points=lambda **kwargs: SimpleNamespace(points=[fake_hit]),
    )
    with patch.object(sparse_searcher, "get_client", return_value=fake_client):
        results = sparse_searcher.search(collection="c", query="查询", top_k=5)
    assert len(results) == 1
    assert results[0].content == "结果内容"
    assert results[0].score == 8.5


def test_search_falls_back_when_collection_has_no_sparse_vector() -> None:
    fake_points = [
        SimpleNamespace(
            id="doc1_0",
            payload={
                "content": "账号 锁定 登录 账号",
                "doc_id": "doc1",
                "chunk_index": 0,
                "category": "paragraph",
            },
        ),
        SimpleNamespace(
            id="doc2_0",
            payload={
                "content": "退款 发票",
                "doc_id": "doc2",
                "chunk_index": 0,
                "category": "paragraph",
            },
        ),
    ]
    fake_client = SimpleNamespace(
        get_collection=lambda _collection: SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(sparse_vectors=None))
        ),
        scroll=lambda **kwargs: (fake_points, None),
    )

    with patch.object(sparse_searcher, "get_client", return_value=fake_client):
        results = sparse_searcher.search(collection="legacy", query="账号登录", top_k=5)

    assert len(results) == 1
    assert results[0].metadata.doc_id == "doc1"


def test_search_raises_qdrant_unavailable_on_failure() -> None:
    from app.core.exceptions import QdrantUnavailable

    def boom(**_):
        raise RuntimeError("net down")

    fake_client = SimpleNamespace(query_points=boom)
    with patch.object(sparse_searcher, "get_client", return_value=fake_client):
        try:
            sparse_searcher.search(collection="c", query="q", top_k=5)
        except QdrantUnavailable as exc:
            assert "sparse search failed" in exc.message
        else:
            raise AssertionError("expected QdrantUnavailable")
