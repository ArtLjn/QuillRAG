"""FastAPI 入口：注册路由，启动时初始化 Qdrant 连接与模型懒加载。

模型加载策略：
- 服务启动时不阻塞预加载（Cross-Encoder 模型 ~2GB，加载慢）
- Embedder 与 Reranker 都是懒加载，首次调用时拉起后台任务
- /health 检查加载状态（loading/ok/unavailable）

启动方式（推荐 → 兜底）：
    # 推荐：在项目根用 uvicorn（自动 reload）
    uvicorn app.main:app --reload --port 8001

    # 兜底：python -m uvicorn
    python -m uvicorn app.main:app --port 8001

    # 应急：直接跑脚本（本文件 __main__ 块会自动修正 sys.path）
    python app/main.py
"""

from __future__ import annotations

# 当作脚本直接运行时（python app/main.py），把项目根加入 sys.path，
# 让后续 `from app.xxx import` 能正确解析。必须在任何 app.* 导入之前。
if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    _project_root = str(Path(__file__).resolve().parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api import (
    collections_router,
    health_router,
    ingest_router,
    parse_router,
    rerank_router,
    retrieve_router,
)
from app.api.auth import router as auth_router
from app.auth.middleware import AuthMiddleware
from app.core.config import settings
from app.core.exceptions import RagServiceError
from app.core.logging import logger
from app.core.metrics import metrics
from app.core.redact import url as redact_url
from app.core.response import ApiResponse
from app.middleware.request_logging import RequestLoggingMiddleware
from app.ui.router import router as ui_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        f"starting quillrag port={settings.port} "
        f"qdrant={redact_url(settings.qdrant_url)} "
        f"embedding={settings.embedding_model} reranker_provider={settings.reranker_provider} "
        f"mineru={'on' if settings.mineru_api_token else 'off'}"
    )
    metrics.counter("quillrag_started", "service start count").inc()
    try:
        from app.storage.metadata_store import MetadataStore

        store = MetadataStore()
        store.init_schema()
        logger.info("metadata sqlite schema initialized")
    except Exception as exc:
        logger.warning(f"metadata store init skipped: {exc!r}")

    yield

    logger.info("quillrag shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="QuillRAG",
        version="0.1.0",
        description="独立 RAG 服务：PDF 复杂解析、混合检索、Cross-Encoder 重排",
        lifespan=lifespan,
    )

    # 请求日志中间件：注入 request_id + 记录 method/path/status/duration
    app.add_middleware(RequestLoggingMiddleware)
    # 鉴权中间件（白名单放行 /health /docs /ui/login 等，其他路径校验 X-API-Key 或 session）
    if settings.auth_enabled:
        app.add_middleware(AuthMiddleware)
        logger.info(
            f"auth enabled: api_key={'on' if settings.auth_api_key else 'off'} "
            f"user={settings.auth_username} session_ttl={settings.auth_session_ttl_hours}h"
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(parse_router)
    app.include_router(ingest_router)
    app.include_router(retrieve_router)
    app.include_router(rerank_router)
    app.include_router(collections_router)
    app.include_router(ui_router)

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    @app.exception_handler(RagServiceError)
    async def handle_rag_error(_: Request, exc: RagServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=ApiResponse.failed(
                message=str(exc.message),
                error_code=exc.error_code,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unknown(_: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"unhandled error: {exc!r}")
        return JSONResponse(
            status_code=500,
            content=ApiResponse.failed(
                message="internal error",
                error_code="INTERNAL_ERROR",
            ).model_dump(),
        )

    return app


app = create_app()


if __name__ == "__main__":
    """支持 `python app/main.py` 直接启动（开发场景）。

    生产推荐用 uvicorn 命令：
        uvicorn app.main:app --host 0.0.0.0 --port 8001
    或在项目根：
        python -m uvicorn app.main:app --reload --port 8001
    """
    import sys
    from pathlib import Path

    # 把项目根（app/ 的父目录）加入 sys.path，让 `from app.xxx` 可解析
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        log_level="info",
    )
