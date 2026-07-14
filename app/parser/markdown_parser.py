"""Markdown 解析器：识别 ATX 标题层级、结构块，并按段落聚合。"""

from __future__ import annotations

import re
from typing import Any

from app.models.chunk import Chunk, ChunkMetadata

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^(```+|~~~+)\s*([A-Za-z0-9_+-]*)?.*$")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


class MarkdownParser:
    file_type = "md"

    async def parse(self, content: bytes | str, metadata: dict[str, Any]) -> list[Chunk]:
        text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        source = metadata.get("source")
        doc_id = metadata.get("doc_id")
        chunks: list[Chunk] = []
        heading_stack: list[str] = []
        buffer: list[str] = []
        current_category = "paragraph"
        current_extra: dict[str, Any] = {}

        def flush(idx_ref: list[int]) -> None:
            if not buffer:
                return
            content_str = "\n".join(buffer).strip()
            if content_str:
                _append_chunk(
                    chunks,
                    content_str,
                    source=source,
                    category=current_category,
                    heading_path=heading_stack,
                    doc_id=doc_id,
                    chunk_index=idx_ref[0],
                    extra=current_extra,
                )
                idx_ref[0] += 1
            buffer.clear()
            current_extra.clear()

        idx_ref = [0]
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.rstrip()
            fence_match = _FENCE_RE.match(line)
            if fence_match:
                flush(idx_ref)
                fence_marker = fence_match.group(1)
                language = fence_match.group(2) or ""
                code_lines = [line]
                i += 1
                while i < len(lines):
                    code_line = lines[i].rstrip()
                    code_lines.append(code_line)
                    if code_line.startswith(fence_marker):
                        break
                    i += 1
                _append_chunk(
                    chunks,
                    "\n".join(code_lines).strip(),
                    source=source,
                    category="code",
                    heading_path=heading_stack,
                    doc_id=doc_id,
                    chunk_index=idx_ref[0],
                    extra={
                        "element_type": "fenced_code",
                        "is_atomic": True,
                        "language": language,
                        "split_reason": "code",
                    },
                )
                idx_ref[0] += 1
                i += 1
                continue

            if _is_table_start(lines, i):
                flush(idx_ref)
                table_lines: list[str] = []
                while i < len(lines):
                    table_line = lines[i].rstrip()
                    if not table_line.strip() or "|" not in table_line:
                        break
                    table_lines.append(table_line)
                    i += 1
                _append_chunk(
                    chunks,
                    "\n".join(table_lines).strip(),
                    source=source,
                    category="table",
                    heading_path=heading_stack,
                    doc_id=doc_id,
                    chunk_index=idx_ref[0],
                    extra={
                        "element_type": "markdown_table",
                        "is_atomic": True,
                        "split_reason": "table",
                        "table_rows": max(0, len(table_lines) - 2),
                        "table_cols": _count_table_columns(table_lines[0]) if table_lines else 0,
                    },
                )
                idx_ref[0] += 1
                continue

            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush(idx_ref)
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack = heading_stack[: level - 1]
                while len(heading_stack) < level - 1:
                    heading_stack.append("")
                heading_stack.append(title)
                _append_chunk(
                    chunks,
                    f"{'#' * level} {title}",
                    source=source,
                    category="title",
                    heading_path=heading_stack,
                    doc_id=doc_id,
                    chunk_index=idx_ref[0],
                    extra={"element_type": "heading", "header_level": level, "split_reason": "heading"},
                )
                idx_ref[0] += 1
                i += 1
                continue

            if _LIST_RE.match(line):
                buffer.append(line)
                current_category = "list"
                current_extra.update({"element_type": "markdown_list", "split_reason": "list"})
                i += 1
                continue

            if not line.strip():
                flush(idx_ref)
                current_category = "paragraph"
                i += 1
                continue

            buffer.append(line)
            current_category = "paragraph"
            i += 1

        flush(idx_ref)
        return chunks


def _append_chunk(
    chunks: list[Chunk],
    content: str,
    *,
    source: str | None,
    category: str,
    heading_path: list[str],
    doc_id: str | None,
    chunk_index: int,
    extra: dict[str, Any] | None = None,
) -> None:
    chunks.append(
        Chunk(
            content=content,
            metadata=ChunkMetadata(
                source=source,
                page=1,
                category=category,
                heading_path=list(heading_path),
                doc_id=doc_id,
                chunk_index=chunk_index,
                extra=dict(extra or {}),
            ),
        )
    )


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    current = lines[index].strip()
    separator = lines[index + 1].strip()
    return "|" in current and bool(_TABLE_SEPARATOR_RE.match(separator))


def _count_table_columns(header_line: str) -> int:
    cells = [cell.strip() for cell in header_line.strip().strip("|").split("|")]
    return len([cell for cell in cells if cell])
