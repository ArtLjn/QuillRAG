"""入库服务：解析 + 分块 + 清洗 + 向量化 + 写入 Qdrant + 写入 SQLite。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

import numpy as np
from qdrant_client.http import models as qmodels

from app.core.exceptions import CollectionNotFound, IngestFailed, QdrantUnavailable
from app.core.logging import logger
from app.models.chunk import Chunk
from app.models.document import DocumentRecord
from app.models.query import ChunkingStrategy
from app.services.parse_service import compute_doc_id, parse_content
from app.storage.collection_manager import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    collection_exists,
    delete_document_points,
    ensure_collection_or_raise,
)
from app.storage.metadata_store import MetadataStore
from app.storage.qdrant_client import get_client
from app.storage.version_manager import VersionManager


async def ingest_content(
    *,
    content: bytes | str,
    collection: str,
    file_type: str | None = None,
    strategy: ChunkingStrategy | str | None = None,
    metadata: dict[str, Any] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    metadata_store: MetadataStore | None = None,
    version_manager: VersionManager | None = None,
    embedder: Any | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    metadata_store = metadata_store or MetadataStore()
    version_manager = version_manager or VersionManager(metadata_store)

    try:
        ensure_collection_or_raise(collection)
    except CollectionNotFound:
        raise
    except Exception as exc:
        raise QdrantUnavailable(f"cannot verify collection {collection}: {exc}") from exc

    raw = content.encode("utf-8", errors="ignore") if isinstance(content, str) else content
    content_hash = hashlib.md5(raw).hexdigest()
    doc_id = metadata.get("doc_id") or compute_doc_id(content)
    metadata["doc_id"] = doc_id

    existing = metadata_store.get_document(doc_id, collection)
    if existing and existing.content_hash == content_hash:
        logger.info(f"ingest skipped: doc_id={doc_id} unchanged")
        return {
            "doc_id": doc_id,
            "chunk_count": existing.chunk_count,
            "collection": collection,
            "action": "noop",
        }

    chunks, _, _, _ = await parse_content(
        content=content,
        file_type=file_type,
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        metadata=metadata,
    )

    if not chunks:
        raise IngestFailed("no chunks produced from content")

    previous_hash = existing.content_hash if existing else None
    if existing:
        try:
            delete_document_points(collection, doc_id)
            logger.info(f"removed old chunks for doc_id={doc_id} before re-ingest")
        except Exception as exc:
            logger.warning(f"failed to remove old chunks for doc_id={doc_id}: {exc!r}")

    try:
        await _write_to_qdrant(collection, doc_id, chunks, embedder=embedder)
    except QdrantUnavailable:
        raise
    except Exception as exc:
        raise IngestFailed(f"failed to write chunks: {exc}") from exc

    record = DocumentRecord(
        doc_id=doc_id,
        collection=collection,
        source=metadata.get("source"),
        category=metadata.get("category"),
        chunk_count=len(chunks),
        content_hash=content_hash,
        extra={
            "file_type": metadata.get("file_type"),
            "strategy": str(strategy) if strategy else "auto",
        },
        ingested_at=datetime.utcnow(),
    )
    metadata_store.upsert_document(record)
    version_manager.record_ingest(record, previous_hash=previous_hash)

    logger.info(f"ingested doc_id={doc_id} collection={collection} chunks={len(chunks)}")
    return {
        "doc_id": doc_id,
        "chunk_count": len(chunks),
        "collection": collection,
        "action": "created" if existing is None else "updated",
    }


async def _write_to_qdrant(
    collection: str,
    doc_id: str,
    chunks: list[Chunk],
    *,
    embedder: Any | None,
) -> None:
    if embedder is None:
        from app.retrieval.embedder import get_embedder

        embedder = get_embedder()

    vectors = await embedder.embed([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise IngestFailed(
            f"embedding count mismatch: chunks={len(chunks)} vectors={len(vectors)}"
        )

    client = get_client()
    dense_vector_name, has_sparse_vector = _resolve_collection_vector_layout(client, collection)
    points: list[qmodels.PointStruct] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        sparse = _build_payload_sparse(chunk.content)
        payload = chunk.to_payload()
        point_id = _make_point_id(doc_id, chunk.metadata.chunk_index)
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector=_build_point_vector(vector, sparse, dense_vector_name, has_sparse_vector),
                payload=payload,
            )
        )

    try:
        client.upsert(collection_name=collection, points=points, wait=True)
    except Exception as exc:
        raise QdrantUnavailable(f"qdrant upsert failed: {exc}") from exc


def _make_point_id(doc_id: str, chunk_index: int) -> str:
    """Qdrant 限制 point id 必须是 unsigned int 或 UUID 字符串。

    用 UUID4 保证唯一性；doc_id 与 chunk_index 写入 payload 中以便后续删除。
    """
    return str(uuid.uuid4())


def _build_payload_sparse(text: str) -> qmodels.SparseVector:
    from app.retrieval.sparse_searcher import build_sparse_vector

    sparse = build_sparse_vector(text)
    return qmodels.SparseVector(
        indices=list(sparse["indices"]),
        values=list(sparse["values"]),
    )


def _resolve_collection_vector_layout(client: Any, collection: str) -> tuple[str | None, bool]:
    """返回 dense 向量名与 sparse 支持状态。

    旧 collection 可能使用 Qdrant 匿名 dense 向量，此时 dense 名称为 None，
    upsert 必须直接写 list，不能写 {"dense": vector}。
    """
    try:
        params = client.get_collection(collection).config.params
    except Exception:
        return DENSE_VECTOR_NAME, True

    vectors = getattr(params, "vectors", None)
    if isinstance(vectors, dict):
        if DENSE_VECTOR_NAME in vectors:
            dense_vector_name = DENSE_VECTOR_NAME
        elif len(vectors) == 1:
            dense_vector_name = next(iter(vectors.keys()))
        else:
            dense_vector_name = DENSE_VECTOR_NAME
    else:
        dense_vector_name = None

    sparse_vectors = getattr(params, "sparse_vectors", None)
    if isinstance(sparse_vectors, dict):
        has_sparse_vector = SPARSE_VECTOR_NAME in sparse_vectors
    else:
        has_sparse_vector = sparse_vectors is not None
    return dense_vector_name, has_sparse_vector


def _build_point_vector(
    dense: list[float],
    sparse: qmodels.SparseVector,
    dense_vector_name: str | None,
    has_sparse_vector: bool,
) -> list[float] | dict[str, Any]:
    if dense_vector_name is None:
        return dense

    vector: dict[str, Any] = {dense_vector_name: dense}
    if has_sparse_vector:
        vector[SPARSE_VECTOR_NAME] = sparse
    return vector


def assert_collection_available(collection: str) -> None:
    if not collection_exists(collection):
        raise CollectionNotFound(f"collection {collection} not found")


def as_numpy(vectors: list[list[float]]) -> np.ndarray:
    return np.asarray(vectors, dtype=np.float32)


__all__ = [
    "assert_collection_available",
    "as_numpy",
    "ingest_content",
]
