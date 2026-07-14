"""查询、检索、重排请求与响应模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.models.chunk import ChunkMetadata


class RetrieveMode(str, Enum):
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"


class ChunkingStrategy(str, Enum):
    STRUCTURE_AWARE = "structure_aware"
    SEMANTIC = "semantic"
    FIXED = "fixed"
    MARKDOWN_STRUCTURE = "markdown_structure"


class RetrieveFilters(BaseModel):
    category: str | None = None
    source: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_qdrant_filter(self) -> dict[str, Any]:
        conditions: list[dict[str, Any]] = []
        if self.category is not None:
            conditions.append({"key": "category", "match": {"value": self.category}})
        if self.source is not None:
            conditions.append({"key": "source", "match": {"value": self.source}})
        for k, v in self.extra.items():
            conditions.append({"key": k, "match": {"value": v}})
        if not conditions:
            return {}
        return {"must": conditions}


class QueryRequest(BaseModel):
    query: str
    collection: str
    mode: RetrieveMode = RetrieveMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=100)
    filters: RetrieveFilters = Field(default_factory=RetrieveFilters)
    use_hyde: bool = False


class RetrieveResult(BaseModel):
    content: str
    score: float
    doc_id: str | None = None
    chunk_index: int = 0
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)


class HyDEConfig(BaseModel):
    enabled: bool = False
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 256


class RetrieveRequest(BaseModel):
    query: str
    collection: str
    mode: RetrieveMode = RetrieveMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    use_hyde: bool = False


class RerankRequest(BaseModel):
    query: str
    documents: list[str] | list[dict[str, Any]] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=100)
    model: str | None = None


class RerankResult(BaseModel):
    content: str
    score: float
    original_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
