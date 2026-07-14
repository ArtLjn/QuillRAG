"""检索服务编排：dense / sparse / hybrid 三模式 + HyDE 改写 + 降级 + 去重。"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import EmbedderUnavailable, InvalidMode, QdrantUnavailable
from app.core.logging import logger
from app.models.query import RetrieveMode, RetrieveResult
from app.retrieval import dense_searcher, hybrid_searcher, sparse_searcher
from app.retrieval.dedup import dedup as dedup_results
from app.retrieval.embedder import get_embedder
from app.retrieval.hyde import maybe_rewrite
from app.storage.metadata_store import MetadataStore


async def retrieve(
    *,
    query: str,
    collection: str,
    mode: RetrieveMode | str,
    top_k: int,
    filters: dict[str, Any] | None = None,
    use_hyde: bool = False,
) -> tuple[list[RetrieveResult], str | None, RetrieveMode]:
    if isinstance(mode, str):
        mode = RetrieveMode(mode)

    effective_query, hyde_warning = await maybe_rewrite(query, use_hyde=use_hyde)

    try:
        if mode == RetrieveMode.VECTOR:
            results, warning, actual_mode = await _retrieve_vector(collection, effective_query, top_k, filters, hyde_warning, mode)
        elif mode == RetrieveMode.BM25:
            results, warning, actual_mode = _retrieve_bm25(collection, effective_query, top_k, filters, hyde_warning, mode)
        elif mode == RetrieveMode.HYBRID:
            results, warning, actual_mode = await _retrieve_hybrid(collection, effective_query, top_k, filters, hyde_warning, mode)
        else:
            raise InvalidMode(f"unknown mode: {mode}")
    except QdrantUnavailable:
        raise
    except EmbedderUnavailable as exc:
        if mode == RetrieveMode.VECTOR:
            logger.warning(f"vector mode embedder unavailable, fallback to bm25: {exc.message}")
            results, warning = _retrieve_bm25_raw(collection, effective_query, top_k, filters)
            results = _filter_visible_documents(collection, results)
            results = _maybe_dedup(results)
            return results, _combine_warnings(hyde_warning, warning, "vector_to_bm25_fallback"), RetrieveMode.BM25
        if mode == RetrieveMode.HYBRID:
            logger.warning(f"hybrid mode embedder unavailable, fallback to bm25: {exc.message}")
            results, warning = _retrieve_bm25_raw(collection, effective_query, top_k, filters)
            results = _filter_visible_documents(collection, results)
            results = _maybe_dedup(results)
            return results, _combine_warnings(hyde_warning, warning, "hybrid_to_bm25_fallback"), RetrieveMode.BM25
        raise

    results = _filter_visible_documents(collection, results)
    results = _maybe_dedup(results)
    return results, warning, actual_mode


def _maybe_dedup(results: list[RetrieveResult]) -> list[RetrieveResult]:
    """Jaccard 去重；若实际去掉了一些结果，添加 warning 标记。"""
    deduped = dedup_results(results)
    if len(deduped) < len(results):
        logger.debug(f"dedup removed {len(results) - len(deduped)} duplicate results")
    return deduped


def _filter_visible_documents(collection: str, results: list[RetrieveResult]) -> list[RetrieveResult]:
    """过滤 SQLite metadata 中已不存在的 doc_id。

    Qdrant 可能残留 orphan points（例如旧删除流程中 metadata 已删但 points 删除失败）。
    当 collection 已有 metadata 记录时，以 metadata 为可见文档清单；若没有任何 metadata
    记录，则保持兼容旧 collection，避免把历史外部数据全部过滤掉。
    """
    if not results:
        return results
    try:
        visible_doc_ids = _load_visible_doc_ids(collection)
    except Exception as exc:
        logger.warning(f"failed to load metadata visibility for collection={collection}: {exc!r}")
        return results

    if not visible_doc_ids:
        return results

    filtered = [result for result in results if result.doc_id in visible_doc_ids]
    removed = len(results) - len(filtered)
    if removed:
        logger.info(f"filtered {removed} orphan retrieval results from collection={collection}")
    return filtered


def _load_visible_doc_ids(collection: str) -> set[str]:
    store = MetadataStore()
    page = 1
    page_size = 1000
    visible: set[str] = set()
    total = 0
    while True:
        total, docs = store.list_documents(collection, page=page, page_size=page_size)
        visible.update(doc.doc_id for doc in docs)
        if len(visible) >= total or not docs:
            break
        page += 1
    return visible if total > 0 else set()


async def _retrieve_vector(
    collection: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
    hyde_warning: str | None,
    original_mode: RetrieveMode,
) -> tuple[list[RetrieveResult], str | None, RetrieveMode]:
    embedder = get_embedder()
    query_vectors = await embedder.embed([query])
    query_vector = query_vectors[0] if query_vectors else []
    results = dense_searcher.search(
        collection=collection,
        query_vector=query_vector,
        top_k=top_k,
        filters=filters,
    )
    return results, hyde_warning, original_mode


def _retrieve_bm25(
    collection: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
    hyde_warning: str | None,
    original_mode: RetrieveMode,
) -> tuple[list[RetrieveResult], str | None, RetrieveMode]:
    results, warning = _retrieve_bm25_raw(collection, query, top_k, filters)
    return results, _combine_warnings(hyde_warning, warning), original_mode


def _retrieve_bm25_raw(
    collection: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
) -> tuple[list[RetrieveResult], str | None]:
    results = sparse_searcher.search(
        collection=collection,
        query=query,
        top_k=top_k,
        filters=filters,
    )
    return results, None


async def _retrieve_hybrid(
    collection: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
    hyde_warning: str | None,
    original_mode: RetrieveMode,
) -> tuple[list[RetrieveResult], str | None, RetrieveMode]:
    try:
        embedder = get_embedder()
        query_vectors = await embedder.embed([query])
        query_vector = query_vectors[0] if query_vectors else []
    except EmbedderUnavailable as exc:
        logger.warning(f"hybrid embedder unavailable, fallback to bm25: {exc.message}")
        results, warning = _retrieve_bm25_raw(collection, query, top_k, filters)
        return results, _combine_warnings(hyde_warning, warning, "hybrid_to_bm25_fallback"), RetrieveMode.BM25

    results = await hybrid_searcher.search(
        collection=collection,
        query=query,
        query_vector=query_vector,
        top_k=top_k,
        filters=filters,
    )
    return results, hyde_warning, original_mode


def _combine_warnings(*parts: str | None) -> str | None:
    cleaned = [p for p in parts if p]
    return ",".join(cleaned) if cleaned else None


__all__ = ["retrieve"]
