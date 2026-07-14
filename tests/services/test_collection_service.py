"""collection_service 单测。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.exceptions import CollectionNotFound, DocumentNotFound
from app.services import collection_service


def test_create_estimates_vector_dim_from_model() -> None:
    with patch("app.services.collection_service.collection_exists", return_value=False), \
         patch("app.services.collection_service.create_collection", return_value={"action": "created"}) as mock_create:
        result = collection_service.create("c1")
    assert result["action"] == "created"
    mock_create.assert_called_once()
    args, kwargs = mock_create.call_args
    assert kwargs["vector_dim"] == 3072  # 默认与 settings.embedding_dim 对齐（gemini-embedding-001）


def test_create_noop_when_exists() -> None:
    with patch("app.services.collection_service.collection_exists", return_value=True):
        result = collection_service.create("c1")
    assert result["action"] == "noop"


def test_remove_raises_when_missing() -> None:
    with patch("app.services.collection_service.collection_exists", return_value=False):
        with pytest.raises(CollectionNotFound):
            collection_service.remove("missing")


def test_remove_cleans_metadata_and_qdrant(tmp_path) -> None:
    from app.storage.metadata_store import MetadataStore

    store = MetadataStore(db_path=str(tmp_path / "c.db"))
    store.init_schema()
    from datetime import datetime

    from app.models.document import DocumentRecord

    store.upsert_document(
        DocumentRecord(
            doc_id="d1",
            collection="c1",
            chunk_count=1,
            content_hash="x",
            ingested_at=datetime.utcnow(),
        )
    )
    with patch("app.services.collection_service.collection_exists", return_value=True), \
         patch("app.services.collection_service.MetadataStore", return_value=store), \
         patch("app.services.collection_service.delete_collection", return_value={"action": "deleted"}):
        result = collection_service.remove("c1")
    assert result["deleted_documents"] == 1


def test_list_documents_raises_when_collection_missing() -> None:
    with patch("app.services.collection_service.collection_exists", return_value=False):
        with pytest.raises(CollectionNotFound):
            collection_service.list_documents("missing")


def test_delete_document_raises_when_doc_missing(tmp_path) -> None:
    from app.storage.metadata_store import MetadataStore

    store = MetadataStore(db_path=str(tmp_path / "d.db"))
    store.init_schema()
    with patch("app.services.collection_service.collection_exists", return_value=True), \
         patch("app.services.collection_service.MetadataStore", return_value=store):
        with pytest.raises(DocumentNotFound):
            collection_service.delete_document("c1", "missing")


def test_delete_document_keeps_metadata_when_qdrant_delete_fails(tmp_path) -> None:
    from datetime import datetime

    from app.core.exceptions import QdrantUnavailable
    from app.models.document import DocumentRecord
    from app.storage.metadata_store import MetadataStore

    store = MetadataStore(db_path=str(tmp_path / "keep.db"))
    store.init_schema()
    store.upsert_document(
        DocumentRecord(
            doc_id="d1",
            collection="c1",
            chunk_count=1,
            content_hash="h",
            ingested_at=datetime.utcnow(),
        )
    )

    with patch("app.services.collection_service.collection_exists", return_value=True), \
         patch("app.services.collection_service.MetadataStore", return_value=store), \
         patch("app.services.collection_service.delete_document_points", side_effect=QdrantUnavailable("down")):
        with pytest.raises(QdrantUnavailable):
            collection_service.delete_document("c1", "d1")

    assert store.get_document("d1", "c1") is not None
