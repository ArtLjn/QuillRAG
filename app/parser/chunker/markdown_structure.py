"""Markdown 结构感知分块。

优先保护 Markdown 结构边界：标题、表格、代码块、列表不被全局语义重组打散。
"""

from __future__ import annotations

import re

from app.models.chunk import Chunk, ChunkMetadata

MAX_MARKDOWN_CHUNK_CHARS = 1200
ATOMIC_CATEGORIES = {"table", "code", "formula", "figure", "list"}
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;])")


def chunk(chunks: list[Chunk], *, max_chars: int = MAX_MARKDOWN_CHUNK_CHARS) -> list[Chunk]:
    if not chunks:
        return []

    result: list[Chunk] = []
    buffer: list[Chunk] = []
    buffer_chars = 0
    current_heading_path: list[str] = []
    chunk_index = 0

    def flush() -> None:
        nonlocal buffer_chars, chunk_index
        if not buffer:
            return

        base = buffer[0].metadata
        merged_body = "\n\n".join(item.content for item in buffer).strip()
        if merged_body:
            content = _with_heading_prefix(merged_body, current_heading_path)
            for piece in _split_oversized_text(content, max_chars):
                result.append(_copy_chunk(piece, base, chunk_index, category="paragraph", heading_path=current_heading_path))
                chunk_index += 1

        buffer.clear()
        buffer_chars = 0

    for item in chunks:
        category = item.metadata.category
        heading_path = list(item.metadata.heading_path)

        if category == "title":
            flush()
            result.append(_copy_chunk(item.content, item.metadata, chunk_index, category="title", heading_path=heading_path))
            chunk_index += 1
            current_heading_path = heading_path
            continue

        if heading_path != current_heading_path:
            flush()
            current_heading_path = heading_path

        if category in ATOMIC_CATEGORIES:
            flush()
            result.append(_copy_chunk(item.content, item.metadata, chunk_index, category=category, heading_path=heading_path))
            chunk_index += 1
            continue

        if buffer and buffer_chars + len(item.content) > max_chars:
            flush()

        buffer.append(item)
        buffer_chars += len(item.content) + 2

    flush()
    _attach_neighbor_ids(result)
    return result


def _copy_chunk(
    content: str,
    base: ChunkMetadata,
    chunk_index: int,
    *,
    category: str,
    heading_path: list[str],
) -> Chunk:
    extra = dict(base.extra)
    extra.setdefault("split_reason", category)
    extra.setdefault("is_atomic", category in ATOMIC_CATEGORIES)
    return Chunk(
        content=content.strip(),
        metadata=ChunkMetadata(
            source=base.source,
            page=base.page,
            category=category,
            heading_path=list(heading_path),
            doc_id=base.doc_id,
            chunk_index=chunk_index,
            extra=extra,
        ),
    )


def _with_heading_prefix(content: str, heading_path: list[str]) -> str:
    if not heading_path:
        return content
    headings = [f"{'#' * min(level, 6)} {title}" for level, title in enumerate(heading_path, start=1) if title]
    prefix = "\n".join(headings).strip()
    if not prefix or content.startswith(prefix):
        return content
    return f"{prefix}\n\n{content}"


def _split_oversized_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    current = ""
    for sentence in [piece.strip() for piece in SENTENCE_BOUNDARY_RE.split(text) if piece.strip()]:
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current.strip())
            current = sentence
            continue
        current = f"{current} {sentence}".strip()

    if current:
        pieces.append(current.strip())

    if not pieces:
        return [text[i : i + max_chars].strip() for i in range(0, len(text), max_chars)]

    result: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            result.append(piece)
            continue
        result.extend(piece[i : i + max_chars].strip() for i in range(0, len(piece), max_chars))
    return [piece for piece in result if piece]


def _attach_neighbor_ids(chunks: list[Chunk]) -> None:
    for item in chunks:
        doc_id = item.metadata.doc_id or ""
        item.metadata.extra["chunk_id"] = f"{doc_id}:{item.metadata.chunk_index}" if doc_id else f"idx:{item.metadata.chunk_index}"

    for index, item in enumerate(chunks):
        if index > 0:
            item.metadata.extra["prev_view_id"] = chunks[index - 1].metadata.extra["chunk_id"]
        if index + 1 < len(chunks):
            item.metadata.extra["next_view_id"] = chunks[index + 1].metadata.extra["chunk_id"]


__all__ = ["ATOMIC_CATEGORIES", "MAX_MARKDOWN_CHUNK_CHARS", "chunk"]
