"""API 路由聚合。"""

from app.api.collections import router as collections_router
from app.api.evaluation import router as evaluation_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.parse import router as parse_router
from app.api.rerank import router as rerank_router
from app.api.retrieve import router as retrieve_router

__all__ = [
    "collections_router",
    "evaluation_router",
    "health_router",
    "ingest_router",
    "parse_router",
    "rerank_router",
    "retrieve_router",
]
