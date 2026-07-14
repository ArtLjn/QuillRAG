"""Sparse 检索（Qdrant 原生 BM25 score，jieba 预分词）。

Qdrant 1.10+ 原生支持 sparse 向量索引（基于 BM25），需要：
1. collection 创建时配置 sparse_vectors_config（已实现）
2. ingest 时写入 sparse 向量（query 的 sparse vector）
3. 检索时调用 query_points 用 sparse 向量查询

Qdrant Python SDK 自 1.10 起提供 `client.query_points(..., sparse_vector=...)`。
新版 SparseVector 输入直接是 {indices: [...], values: [...]}。

但 Qdrant 服务端会自动用文档 payload 中的文本生成 sparse 向量（如果配置了 text-sparse 字段），
 ingest 时只要写入 payload 即可（payload 中包含 content 字段）。
查询时，需要客户端用 BM25 tokenizer 自己生成 sparse_vector。

简化方案：
- 服务端：collection 配置 sparse index，ingest 时只写 payload + dense
- 客户端：sparse_searcher 用 jieba 分词构造 sparse vector 调用 query_points

如果 Qdrant 不支持本地 sparse 生成（早期版本），降级为 rank_bm25 检索（从 Qdrant 拉全部文档 + 客户端打分）。
"""

from __future__ import annotations

import hashlib
from typing import Any

import jieba

from app.core.exceptions import QdrantUnavailable
from app.core.logging import logger
from app.models.chunk import ChunkMetadata
from app.models.query import RetrieveResult
from app.storage.collection_manager import SPARSE_VECTOR_NAME
from app.storage.qdrant_client import get_client

try:
    from qdrant_client.http import models as qmodels
except ImportError:  # pragma: no cover
    qmodels = None  # type: ignore[assignment]


def tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


def build_sparse_vector(text: str) -> dict[str, list[int] | list[float]]:
    """构造 Qdrant SparseVector：{indices: [...], values: [...]}。"""
    tokens = tokenize(text)
    if not tokens:
        return {"indices": [], "values": []}
    counts: dict[int, float] = {}
    for tok in tokens:
        idx = _hash_index(tok)
        counts[idx] = counts.get(idx, 0.0) + 1.0
    indices = sorted(counts.keys())
    values = [counts[i] for i in indices]
    return {"indices": indices, "values": values}


def _hash_index(token: str) -> int:
    """稳定哈希到 [0, 2^31)。Qdrant 要求 uint32 索引。"""
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % (2**31)


def search(
    *,
    collection: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None = None,
) -> list[RetrieveResult]:
    client = get_client()
    sparse = build_sparse_vector(query)
    if not sparse["indices"]:
        return []

    qdrant_filter = _build_filter(filters)
    if not _has_sparse_vector(client, collection):
        return _fallback_payload_search(client, collection, query, top_k, qdrant_filter)

    sparse_vector = qmodels.SparseVector(indices=sparse["indices"], values=sparse["values"]) if qmodels else sparse

    try:
        response = client.query_points(
            collection_name=collection,
            query=sparse_vector,
            using=SPARSE_VECTOR_NAME,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        hits = response.points
    except Exception as exc:
        raise QdrantUnavailable(f"sparse search failed: {exc}") from exc

    return _hits_to_results(hits)


def _has_sparse_vector(client: Any, collection: str) -> bool:
    try:
        sparse_vectors = client.get_collection(collection).config.params.sparse_vectors
    except Exception:
        return True
    if isinstance(sparse_vectors, dict):
        return SPARSE_VECTOR_NAME in sparse_vectors
    return sparse_vectors is not None


def _fallback_payload_search(
    client: Any,
    collection: str,
    query: str,
    top_k: int,
    qdrant_filter: Any,
) -> list[RetrieveResult]:
    """旧 collection 没有 sparse 向量时，从 payload 拉文本做轻量词频检索。"""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    try:
        points, _ = client.scroll(
            collection_name=collection,
            scroll_filter=qdrant_filter,
            limit=10000,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        raise QdrantUnavailable(f"sparse fallback search failed: {exc}") from exc

    scored: list[Any] = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        content = payload.get("content", "") if isinstance(payload, dict) else ""
        score = _term_score(query_tokens, content)
        if score > 0:
            scored.append(
                type(
                    "FallbackHit",
                    (),
                    {
                        "id": getattr(point, "id", None),
                        "score": score,
                        "payload": dict(payload),
                    },
                )()
            )
    scored.sort(key=lambda item: item.score, reverse=True)
    return _hits_to_results(scored[:top_k])


def _term_score(query_tokens: list[str], content: str) -> float:
    content_tokens = tokenize(content)
    if not content_tokens:
        return 0.0
    content_set = set(content_tokens)
    score = 0.0
    for token in query_tokens:
        if token in content_set:
            score += 1.0 + content_tokens.count(token) / max(1, len(content_tokens))
    return score


def _build_filter(filters: dict[str, Any] | None) -> Any:
    if not filters or qmodels is None:
        return None
    conditions: list[Any] = []
    must_dict = filters.get("must", {}) if "must" in filters else filters
    if isinstance(must_dict, dict):
        for key, value in must_dict.items():
            conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value)))
    if not conditions:
        return None
    return qmodels.Filter(must=conditions)


def _hits_to_results(hits: list[Any]) -> list[RetrieveResult]:
    results: list[RetrieveResult] = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        content = payload.pop("content", "") if isinstance(payload, dict) else ""
        metadata = ChunkMetadata.from_qdrant_payload(payload if isinstance(payload, dict) else {})
        results.append(
            RetrieveResult(
                content=content,
                score=float(getattr(hit, "score", 0.0)),
                doc_id=metadata.doc_id,
                chunk_index=metadata.chunk_index,
                metadata=metadata,
            )
        )
    logger.debug(f"sparse search returned {len(results)} hits")
    return results


__all__ = ["build_sparse_vector", "search", "tokenize"]
