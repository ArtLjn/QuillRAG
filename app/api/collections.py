"""collections CRUD 与文档管理。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.response import ApiResponse
from app.services import collection_service

router = APIRouter(prefix="/collections", tags=["collections"])


class CreateCollectionBody(BaseModel):
    name: str
    vector_dim: int | None = None
    distance: str = "Cosine"


@router.post("")
async def create_collection_endpoint(body: CreateCollectionBody) -> ApiResponse[dict[str, Any]]:
    result = collection_service.create(body.name, vector_dim=body.vector_dim, distance=body.distance)
    return ApiResponse.ok(result)


@router.get("")
async def list_collections_endpoint() -> ApiResponse[list[dict[str, Any]]]:
    return ApiResponse.ok(collection_service.list_all())


@router.delete("/{name}")
async def delete_collection_endpoint(name: str) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(collection_service.remove(name))


@router.post("/{name}/prune-orphans")
async def prune_orphan_points_endpoint(
    name: str,
    dry_run: bool = Query(default=False),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(collection_service.prune_orphan_points(name, dry_run=dry_run))


@router.get("/{name}/documents")
async def list_documents_endpoint(
    name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[dict[str, Any]]:
    result = collection_service.list_documents(name, page=page, page_size=page_size)
    return ApiResponse.ok(result)


@router.delete("/{name}/documents/{doc_id}")
async def delete_document_endpoint(name: str, doc_id: str) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(collection_service.delete_document(name, doc_id))


__all__ = [
    "CreateCollectionBody",
    "create_collection_endpoint",
    "delete_collection_endpoint",
    "delete_document_endpoint",
    "list_collections_endpoint",
    "list_documents_endpoint",
    "prune_orphan_points_endpoint",
]
