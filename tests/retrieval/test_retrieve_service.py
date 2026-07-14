"""retrieve_service 完整流程单测：覆盖三种 mode + 降级。"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.core.exceptions import EmbedderUnavailable, QdrantUnavailable
from app.models.chunk import ChunkMetadata
from app.models.document import DocumentRecord
from app.models.query import RetrieveMode, RetrieveResult
from app.services import retrieve_service


def _result(doc_id: str, idx: int, score: float) -> RetrieveResult:
    return RetrieveResult(
        content=f"{doc_id}-{idx}",
        score=score,
        doc_id=doc_id,
        chunk_index=idx,
        metadata=ChunkMetadata(doc_id=doc_id, chunk_index=idx),
    )


def _patch_searchers(dense_returns: list | None = None, sparse_returns: list | None = None) -> None:
    from app.retrieval import dense_searcher, sparse_searcher

    if dense_returns is not None:
        patch.object(dense_searcher, "search", lambda **_: dense_returns).start()
    if sparse_returns is not None:
        patch.object(sparse_searcher, "search", lambda **_: sparse_returns).start()


def test_bm25_mode_returns_results_without_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    sparse = [_result("doc", 0, 5.0)]
    with patch("app.retrieval.sparse_searcher.search", lambda **kw: sparse):
        results, warning, mode = asyncio.get_event_loop().run_until_complete(
            retrieve_service.retrieve(
                query="q",
                collection="c",
                mode=RetrieveMode.BM25,
                top_k=5,
            )
        )
    assert mode == RetrieveMode.BM25
    assert results == sparse
    assert warning is None


def test_retrieve_filters_deleted_documents_when_metadata_exists(tmp_path) -> None:
    from datetime import datetime

    from app.storage.metadata_store import MetadataStore

    store = MetadataStore(db_path=str(tmp_path / "retrieve.db"))
    store.init_schema()
    store.upsert_document(
        DocumentRecord(
            doc_id="alive",
            collection="c",
            chunk_count=1,
            content_hash="h",
            ingested_at=datetime.utcnow(),
        )
    )
    sparse = [_result("deleted", 0, 5.0), _result("alive", 0, 4.0)]

    with patch("app.services.retrieve_service.MetadataStore", return_value=store), \
         patch("app.retrieval.sparse_searcher.search", lambda **kw: sparse):
        results, _, _ = asyncio.get_event_loop().run_until_complete(
            retrieve_service.retrieve(
                query="q",
                collection="c",
                mode=RetrieveMode.BM25,
                top_k=5,
            )
        )

    assert [result.doc_id for result in results] == ["alive"]


def test_retrieve_keeps_results_when_collection_has_no_metadata_records(tmp_path) -> None:
    from app.storage.metadata_store import MetadataStore

    store = MetadataStore(db_path=str(tmp_path / "empty.db"))
    store.init_schema()
    sparse = [_result("legacy", 0, 5.0)]

    with patch("app.services.retrieve_service.MetadataStore", return_value=store), \
         patch("app.retrieval.sparse_searcher.search", lambda **kw: sparse):
        results, _, _ = asyncio.get_event_loop().run_until_complete(
            retrieve_service.retrieve(
                query="q",
                collection="legacy",
                mode=RetrieveMode.BM25,
                top_k=5,
            )
        )

    assert [result.doc_id for result in results] == ["legacy"]


def test_vector_mode_falls_back_to_bm25_when_embedder_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom_embed(self, texts):
        raise EmbedderUnavailable("no model")

    sparse_results = [_result("doc", 1, 5.0)]
    with patch("app.services.retrieve_service.get_embedder") as mock_get, \
         patch("app.retrieval.sparse_searcher.search", lambda **kw: sparse_results):
        bad = type("Bad", (), {"embed": boom_embed, "embed_query": lambda self, t: (_ for _ in ()).throw(EmbedderUnavailable("no model"))})()
        mock_get.return_value = bad
        results, warning, mode = asyncio.get_event_loop().run_until_complete(
            retrieve_service.retrieve(
                query="q",
                collection="c",
                mode=RetrieveMode.VECTOR,
                top_k=5,
            )
        )
    assert mode == RetrieveMode.BM25
    assert "vector_to_bm25_fallback" in (warning or "")
    assert results == sparse_results


def test_hybrid_mode_uses_dense_and_sparse(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.retrieval import dense_searcher, sparse_searcher

    dense_results = [_result("d", 0, 0.9), _result("d", 1, 0.85)]
    sparse_results = [_result("d", 0, 5.0), _result("d", 2, 4.0)]

    async def fake_embed(self, texts):
        return [[0.1] * 8 for _ in texts]

    fake_embedder = type(
        "Ok",
        (),
        {
            "embed": fake_embed,
            "embed_query": lambda self, text: [0.1] * 8,
            "is_ready": lambda self: True,
            "state": "ready",
        },
    )()

    with patch("app.services.retrieve_service.get_embedder", return_value=fake_embedder), \
         patch.object(dense_searcher, "search", lambda **kw: dense_results), \
         patch.object(sparse_searcher, "search", lambda **kw: sparse_results):
        results, warning, mode = asyncio.get_event_loop().run_until_complete(
            retrieve_service.retrieve(
                query="q",
                collection="c",
                mode=RetrieveMode.HYBRID,
                top_k=5,
            )
        )
    assert mode == RetrieveMode.HYBRID
    assert results
    assert results[0].doc_id == "d"


def test_hybrid_raises_qdrant_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.retrieval import dense_searcher, sparse_searcher

    def boom(**_):
        raise QdrantUnavailable("down")

    async def fake_embed(self, texts):
        return [[0.1] * 8 for _ in texts]

    with patch("app.retrieval.embedder.get_embedder") as mock_get, \
         patch.object(dense_searcher, "search", boom), \
         patch.object(sparse_searcher, "search", boom):
        mock_get.return_value = type("Ok", (), {"embed": fake_embed, "embed_query": lambda self, t: [0.1] * 8})()
        try:
            asyncio.get_event_loop().run_until_complete(
                retrieve_service.retrieve(
                    query="q",
                    collection="c",
                    mode=RetrieveMode.HYBRID,
                    top_k=5,
                )
            )
        except QdrantUnavailable:
            pass
        else:
            raise AssertionError("expected QdrantUnavailable")
