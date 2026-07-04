"""quillrag 业务异常基类与子类。

约定：
- 抛 RagServiceError 子类时附带 `error_code` 与 `http_status`
- API 层统一捕获后转为 `{code: FAILED, message, error_code}` 响应
"""

from __future__ import annotations


class RagServiceError(Exception):
    error_code: str = "RAG_SERVICE_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", *, error_code: str | None = None, http_status: int | None = None) -> None:
        super().__init__(message or self.error_code)
        self.message = message or self.error_code
        if error_code is not None:
            self.error_code = error_code
        if http_status is not None:
            self.http_status = http_status


class ParseFailed(RagServiceError):
    error_code = "PARSE_FAILED"
    http_status = 422


class UnsupportedFormat(RagServiceError):
    error_code = "UNSUPPORTED_FORMAT"
    http_status = 400


class CollectionNotFound(RagServiceError):
    error_code = "COLLECTION_NOT_FOUND"
    http_status = 404


class CollectionAlreadyExists(RagServiceError):
    error_code = "COLLECTION_ALREADY_EXISTS"
    http_status = 409


class IngestFailed(RagServiceError):
    error_code = "INGEST_FAILED"
    http_status = 422


class QdrantUnavailable(RagServiceError):
    error_code = "QDRANT_UNAVAILABLE"
    http_status = 503


class ModelUnavailable(RagServiceError):
    error_code = "MODEL_UNAVAILABLE"
    http_status = 507


class RerankerUnavailable(ModelUnavailable):
    error_code = "RERANKER_MODEL_UNAVAILABLE"


class EmbedderUnavailable(ModelUnavailable):
    error_code = "EMBEDDER_MODEL_UNAVAILABLE"


class InvalidMode(RagServiceError):
    error_code = "INVALID_MODE"
    http_status = 400


class DocumentNotFound(RagServiceError):
    error_code = "DOCUMENT_NOT_FOUND"
    http_status = 404
