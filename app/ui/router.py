"""UI 路由：Jinja2 渲染 + TailwindCSS CDN，零前端构建。

页面：
- GET /ui/                              首页（collections 总览）
- GET /ui/collections/{name}            collection 文档列表
- GET /ui/collections/{name}/documents/{doc_id}  文档 chunks 详情
- GET /ui/retrieve                      检索调试器
- GET /ui/health                        健康检查可视化
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from qdrant_client.http import models as qmodels

from app.evaluation.runner import load_latest_report
from app.services import collection_service
from app.services.health_service import check_health
from app.storage.collection_manager import ensure_collection_or_raise
from app.storage.qdrant_client import get_client

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/ui", tags=["ui"], default_response_class=HTMLResponse)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    collections = collection_service.list_all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"collections": collections, "title": "quillrag · Collections"},
    )


@router.get("/collections/new", response_class=HTMLResponse)
async def collection_new_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "collection_new.html",
        {
            "title": "新建 Collection",
            "collections": collection_service.list_all(),
        },
    )


@router.get("/collections/{name}", response_class=HTMLResponse)
async def collection_detail(
    request: Request,
    name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> HTMLResponse:
    try:
        listing = collection_service.list_documents(name, page=page, page_size=page_size)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    total_pages = max(1, (listing["total"] + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "name": name,
            "documents": listing["documents"],
            "total": listing["total"],
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "title": f"Collection · {name}",
        },
    )


@router.get("/collections/{name}/documents/{doc_id}", response_class=HTMLResponse)
async def document_chunks(request: Request, name: str, doc_id: str) -> HTMLResponse:
    """从 Qdrant 拉该 doc_id 的所有 chunk（按 logic_idx 排序）。"""
    try:
        ensure_collection_or_raise(name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    client = get_client()
    try:
        result = client.scroll(
            collection_name=name,
            scroll_filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
            ),
            limit=10000,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"qdrant error: {exc}") from exc

    points = list(result[0])
    chunks = _sort_chunks(points)
    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "name": name,
            "doc_id": doc_id,
            "chunks": chunks,
            "title": f"Document · {doc_id[:8]}",
        },
    )


@router.get("/retrieve", response_class=HTMLResponse)
async def retrieve_debug(request: Request) -> HTMLResponse:
    collections = _prefer_ticket_knowledge(collection_service.list_all())
    return templates.TemplateResponse(
        request,
        "retrieve.html",
        {
            "title": "检索调试器",
            "collections": collections,
        },
    )


@router.get("/ingest", response_class=HTMLResponse)
async def ingest_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "ingest.html",
        {
            "title": "入库新文档",
            "collections": collection_service.list_all(),
        },
    )


@router.get("/evaluation", response_class=HTMLResponse)
async def evaluation_dashboard(request: Request) -> HTMLResponse:
    report = load_latest_report()
    return templates.TemplateResponse(
        request,
        "evaluation.html",
        {
            "title": "RAG 召回评测",
            "report": report,
            "available": report is not None,
        },
    )


@router.get("/health", response_class=HTMLResponse)
async def health_visualize(request: Request) -> HTMLResponse:
    health = await check_health()
    return templates.TemplateResponse(
        request,
        "health.html",
        {"health": health, "title": "Health"},
    )


def _sort_chunks(points: list[Any]) -> list[dict[str, Any]]:
    """按 logic_idx → page → chunk_index 排序 chunk。"""
    items: list[dict[str, Any]] = []
    for p in points:
        payload = p.payload or {}
        items.append(
            {
                "id": str(p.id),
                "content": payload.get("content", ""),
                "category": payload.get("category", "paragraph"),
                "page": payload.get("page"),
                "chunk_index": payload.get("chunk_index", 0),
                "heading_path": payload.get("heading_path", []),
                "logic_idx": payload.get("logic_idx"),
                "prev_view_id": payload.get("prev_view_id"),
                "next_view_id": payload.get("next_view_id"),
                "extra": {k: v for k, v in payload.items() if k not in {"content", "category", "page", "chunk_index", "heading_path", "logic_idx", "prev_view_id", "next_view_id", "doc_id", "source"}},
            }
        )
    items.sort(key=lambda c: (c.get("logic_idx") if c.get("logic_idx") is not None else 99999, c.get("page") or 0, c["chunk_index"]))
    return items


def _prefer_ticket_knowledge(collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        collections,
        key=lambda item: (0 if item.get("name") == "ticket_knowledge" else 1, item.get("name") or ""),
    )


__all__ = ["router", "templates"]
