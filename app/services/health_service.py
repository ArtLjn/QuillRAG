"""健康检查服务：聚合 Qdrant / Embedder / Reranker 三组件状态。

状态语义：
- "ok"         组件就绪
- "idle"       懒加载未触发（首次调用 API 时启动）
- "loading"    后台加载中
- "disabled"   用户主动关闭（reranker 默认 disabled）
- "failed"     加载失败
- "unavailable" 连接异常

degraded 判定：只有 "failed" / "unavailable" 算 degraded
- "idle" / "loading" 是懒加载正常状态，不算 degraded
"""

from __future__ import annotations

from app.core.logging import logger
from app.core.response import HealthResponse

DEGRADED_STATES = {"failed", "unavailable"}


async def check_health() -> HealthResponse:
    components: dict[str, str] = {}

    components["qdrant"] = await _check_qdrant()
    components["embedder"] = await _check_embedder()
    components["reranker"] = await _check_reranker()

    degraded = [name for name, status in components.items() if status in DEGRADED_STATES]
    status = "degraded" if degraded else "ok"
    warning = f"degraded components: {', '.join(degraded)}" if degraded else None
    if warning:
        logger.warning(f"rag-service health degraded: {components}")
    return HealthResponse(status=status, components=components, warning=warning)


async def _check_qdrant() -> str:
    try:
        from app.storage.qdrant_client import get_client

        client = get_client()
        client.get_collections()
        return "ok"
    except Exception as exc:
        logger.debug(f"qdrant health check failed: {exc!r}")
        return "unavailable"


async def _check_embedder() -> str:
    """embedder 状态映射：
    - state="ready"  → "ok"
    - state="failed" → "failed"
    - state="idle"   → "idle"（懒加载未触发，正常）
    - state="probing"→ "loading"
    """
    try:
        from app.retrieval.embedder import get_embedder

        embedder = get_embedder()
        state = getattr(embedder, "state", "idle")
        return {
            "ready": "ok",
            "failed": "failed",
            "idle": "idle",
            "probing": "loading",
        }.get(state, "loading")
    except Exception as exc:
        logger.debug(f"embedder health check failed: {exc!r}")
        return "unavailable"


async def _check_reranker() -> str:
    """reranker 状态映射：
    - provider="disabled" → "disabled"
    - state="ready"       → "ok"
    - state="failed"      → "failed"
    - state="idle"        → "idle"
    - state="loading"     → "loading"
    """
    try:
        from app.retrieval.reranker import get_reranker

        reranker = get_reranker()
        if getattr(reranker, "provider", "") == "disabled":
            return "disabled"
        if reranker.is_ready():
            return "ok"
        if getattr(reranker, "is_failed", lambda: False)():
            return "failed"
        state = getattr(reranker, "state", "idle")
        return {
            "ready": "ok",
            "failed": "failed",
            "idle": "idle",
            "disabled": "disabled",
            "loading": "loading",
        }.get(state, "loading")
    except Exception as exc:
        logger.debug(f"reranker health check failed: {exc!r}")
        return "unavailable"
