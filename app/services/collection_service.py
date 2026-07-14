"""collection 与文档管理服务。"""

from __future__ import annotations

from typing import Any

from qdrant_client.http import models as qmodels

from app.core.exceptions import CollectionNotFound, DocumentNotFound
from app.core.logging import logger
from app.retrieval.embedder import estimate_vector_dim
from app.storage.collection_manager import (
    collection_exists,
    create_collection,
    delete_collection,
    delete_document_points,
    list_collections,
)
from app.storage.metadata_store import MetadataStore
from app.storage.qdrant_client import get_client


def create(collection: str, vector_dim: int | None = None, distance: str = "Cosine") -> dict[str, Any]:
    dim = vector_dim or estimate_vector_dim(_active_embedding_model())
    if not collection_exists(collection):
        result = create_collection(collection, vector_dim=dim, distance=distance)
        result["vector_dim"] = dim
        return result
    return {"collection": collection, "action": "noop", "vector_dim": dim}


def remove(collection: str) -> dict[str, Any]:
    if not collection_exists(collection):
        raise CollectionNotFound(f"collection {collection} not found")
    store = MetadataStore()
    deleted_docs = store.delete_collection_documents(collection)
    result = delete_collection(collection)
    result["deleted_documents"] = deleted_docs
    logger.info(f"removed collection {collection}, cleaned {deleted_docs} metadata records")
    return result


def list_all() -> list[dict[str, Any]]:
    return list_collections()


def list_documents(
    collection: str,
    *,
    page: int = 1,
    page_size: int = 20,
    store: MetadataStore | None = None,
) -> dict[str, Any]:
    if not collection_exists(collection):
        raise CollectionNotFound(f"collection {collection} not found")
    store = store or MetadataStore()
    total, docs = store.list_documents(collection, page=page, page_size=page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "documents": [d.model_dump(mode="json") for d in docs],
    }


def delete_document(collection: str, doc_id: str, store: MetadataStore | None = None) -> dict[str, Any]:
    if not collection_exists(collection):
        raise CollectionNotFound(f"collection {collection} not found")
    store = store or MetadataStore()
    existing = store.get_document(doc_id, collection)
    if not existing:
        raise DocumentNotFound(f"document {doc_id} not found in collection {collection}")
    points_removed = delete_document_points(collection, doc_id)
    deleted = store.delete_document(doc_id, collection)
    logger.info(f"deleted document {doc_id} from {collection}: meta={deleted} points={points_removed}")
    return {
        "doc_id": doc_id,
        "collection": collection,
        "metadata_removed": deleted,
        "points_removed": points_removed,
    }


def prune_orphan_points(collection: str, *, dry_run: bool = False, store: MetadataStore | None = None) -> dict[str, Any]:
    """删除 Qdrant 中已无 SQLite metadata 对应记录的孤儿 points。"""
    if not collection_exists(collection):
        raise CollectionNotFound(f"collection {collection} not found")

    store = store or MetadataStore()
    visible_doc_ids = _load_visible_doc_ids(collection, store)
    client = get_client()

    orphan_point_ids: list[Any] = []
    orphan_doc_ids: set[str] = set()
    next_offset: Any | None = None
    scanned = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=10000,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        scanned += len(points)
        for point in points:
            payload = getattr(point, "payload", None) or {}
            doc_id = payload.get("doc_id") if isinstance(payload, dict) else None
            if doc_id not in visible_doc_ids:
                orphan_point_ids.append(point.id)
                orphan_doc_ids.add(str(doc_id or "<missing>"))
        if next_offset is None:
            break

    points_removed = 0
    if orphan_point_ids and not dry_run:
        client.delete(
            collection_name=collection,
            points_selector=qmodels.PointIdsList(points=orphan_point_ids),
        )
        points_removed = len(orphan_point_ids)

    result = {
        "collection": collection,
        "dry_run": dry_run,
        "scanned_points": scanned,
        "visible_document_count": len(visible_doc_ids),
        "orphan_doc_ids": sorted(orphan_doc_ids),
        "orphan_point_count": len(orphan_point_ids),
        "points_removed": points_removed,
    }
    logger.info(
        f"pruned orphan points collection={collection} dry_run={dry_run} "
        f"scanned={scanned} orphan_points={len(orphan_point_ids)} removed={points_removed}"
    )
    return result


def _load_visible_doc_ids(collection: str, store: MetadataStore) -> set[str]:
    page = 1
    page_size = 1000
    visible: set[str] = set()
    while True:
        total, docs = store.list_documents(collection, page=page, page_size=page_size)
        visible.update(doc.doc_id for doc in docs)
        if len(visible) >= total or not docs:
            break
        page += 1
    return visible


def _active_embedding_model() -> str:
    from app.core.config import settings

    return settings.embedding_model


def client() -> Any:
    return get_client()


__all__ = [
    "client",
    "create",
    "delete_document",
    "list_all",
    "list_documents",
    "prune_orphan_points",
    "remove",
]
