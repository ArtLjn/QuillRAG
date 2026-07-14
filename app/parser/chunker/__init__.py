"""分块策略选择器与三种策略实现。"""

from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.models.chunk import Chunk
from app.models.query import ChunkingStrategy

__all__ = ["chunk_with_strategy", "select_default_strategy"]


def select_default_strategy(file_type: str) -> ChunkingStrategy:
    normalized = (file_type or "").lower().lstrip(".")
    if normalized == "pdf":
        return ChunkingStrategy.STRUCTURE_AWARE
    if normalized in {"md", "markdown"}:
        return ChunkingStrategy.MARKDOWN_STRUCTURE
    return ChunkingStrategy.FIXED


def chunk_with_strategy(
    chunks: list[Chunk],
    strategy: ChunkingStrategy | str,
    *,
    file_type: str | None = None,
    options: dict[str, Any] | None = None,
) -> list[Chunk]:
    options = options or {}
    if isinstance(strategy, str):
        strategy = ChunkingStrategy(strategy)

    if not chunks:
        return []

    if strategy == ChunkingStrategy.STRUCTURE_AWARE:
        from app.parser.chunker.structure_aware import chunk as do_chunk

        max_chars = options.get("max_chars")
        return do_chunk(chunks, max_chars=max_chars) if max_chars else do_chunk(chunks)

    if strategy == ChunkingStrategy.SEMANTIC:
        from app.parser.chunker.semantic import chunk as do_chunk

        return do_chunk(chunks)

    if strategy == ChunkingStrategy.MARKDOWN_STRUCTURE:
        from app.parser.chunker.markdown_structure import chunk as do_chunk

        max_chars = options.get("max_chars")
        return do_chunk(chunks, max_chars=max_chars) if max_chars else do_chunk(chunks)

    if strategy == ChunkingStrategy.FIXED:
        from app.parser.chunker.fixed import chunk as do_chunk

        return do_chunk(
            chunks,
            chunk_size=options.get("chunk_size"),
            overlap=options.get("chunk_overlap"),
        )

    logger.warning(f"unknown chunking strategy {strategy}, fallback to fixed")
    from app.parser.chunker.fixed import chunk as do_chunk

    return do_chunk(chunks)
