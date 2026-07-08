"""dense_searcher 单测：mock qdrant client，验证 score_threshold 过滤与 payload 解析。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.retrieval import dense_searcher


def _make_hit(score: float, content: str, doc_id: str, chunk_index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"{doc_id}_{chunk_index}",
        score=score,
        payload={
            "content": content,
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "category": "paragraph",
            "heading_path": [],
            "source": "test.pdf",
            "page": 1,
        },
    )


def test_dense_search_returns_payload_parsed_results() -> None:
    fake_client = SimpleNamespace(
        query_points=lambda **kwargs: SimpleNamespace(
            points=[
                _make_hit(0.91, "命中1", "doc1", 0),
                _make_hit(0.45, "命中2", "doc2", 1),
            ]
        )
    )

    with patch.object(dense_searcher, "get_client", return_value=fake_client):
        results = dense_searcher.search(
            collection="c",
            query_vector=[0.1] * 8,
            top_k=5,
            score_threshold=0.0,
        )

    assert len(results) == 2
    assert results[0].content == "命中1"
    assert results[0].metadata.doc_id == "doc1"


def test_dense_search_passes_score_threshold_to_qdrant() -> None:
    captured: dict = {}

    def fake_query_points(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(points=[])

    fake_client = SimpleNamespace(query_points=fake_query_points)
    with patch.object(dense_searcher, "get_client", return_value=fake_client):
        dense_searcher.search(
            collection="c",
            query_vector=[0.1] * 4,
            top_k=10,
            score_threshold=0.7,
        )
    assert captured["score_threshold"] == 0.7
    assert captured["limit"] == 10
    assert captured["using"] == "dense"


def test_dense_search_omits_using_for_legacy_unnamed_vector() -> None:
    captured: dict = {}

    def fake_query_points(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(points=[])

    fake_client = SimpleNamespace(
        query_points=fake_query_points,
        get_collection=lambda _collection: SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=SimpleNamespace(size=3072, distance="Cosine")
                )
            )
        ),
    )
    with patch.object(dense_searcher, "get_client", return_value=fake_client):
        dense_searcher.search(
            collection="legacy",
            query_vector=[0.1] * 4,
            top_k=10,
            score_threshold=0.7,
        )

    assert "using" not in captured


def test_dense_search_raises_qdrant_unavailable_on_failure() -> None:
    from app.core.exceptions import QdrantUnavailable

    def boom(**_):
        raise RuntimeError("network down")

    fake_client = SimpleNamespace(query_points=boom)
    with patch.object(dense_searcher, "get_client", return_value=fake_client):
        try:
            dense_searcher.search(
                collection="c",
                query_vector=[0.1] * 4,
                top_k=5,
            )
        except QdrantUnavailable as exc:
            assert "dense search failed" in exc.message
        else:
            raise AssertionError("expected QdrantUnavailable")
