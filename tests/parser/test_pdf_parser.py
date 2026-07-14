"""PDF parser 单测。

由于真实 PDF 解析依赖 PyMuPDF 与版面启发式，测试用最小化的「假 PDF bytes」，
覆盖失败路径；并 mock fitz.open 验证 happy path。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models.chunk import Chunk


def test_pdf_parser_requires_pymupdf(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parser import pdf_parser

    monkeypatch.setattr(pdf_parser, "fitz", None)
    monkeypatch.setattr(pdf_parser, "_IMPORT_ERROR", RuntimeError("no fitz"))

    parser = pdf_parser.PdfParser()
    with pytest.raises(pdf_parser.ParseFailed):
        import asyncio

        asyncio.get_event_loop().run_until_complete(parser.parse(b"%PDF-1.4 test", {"doc_id": "x"}))


def test_layout_summary_counts_categories() -> None:
    from app.parser import pdf_parser

    chunks = [
        Chunk.model_validate({"content": "T1", "metadata": {"category": "title"}}),
        Chunk.model_validate({"content": "P1", "metadata": {"category": "paragraph"}}),
        Chunk.model_validate({"content": "T2", "metadata": {"category": "table"}}),
    ]
    summary = pdf_parser.layout_summary(chunks)
    assert summary["title"] == 1
    assert summary["paragraph"] == 1
    assert summary["table"] == 1
    assert summary["total"] == 3


def test_text_parser_splits_paragraphs(sample_text: str) -> None:
    import asyncio

    from app.parser.text_parser import TextParser

    chunks = asyncio.get_event_loop().run_until_complete(TextParser().parse(sample_text, {"doc_id": "t"}))
    assert len(chunks) == 3
    assert all(c.metadata.category == "paragraph" for c in chunks)


def test_markdown_parser_extracts_headings(sample_markdown: str) -> None:
    import asyncio

    from app.parser.markdown_parser import MarkdownParser

    chunks = asyncio.get_event_loop().run_until_complete(
        MarkdownParser().parse(sample_markdown, {"doc_id": "m"})
    )
    titles = [c for c in chunks if c.metadata.category == "title"]
    assert len(titles) >= 3
    assert any("项目说明" in c.content for c in titles)


def test_markdown_parser_extracts_tables_as_atomic_chunks() -> None:
    import asyncio

    from app.parser.markdown_parser import MarkdownParser

    markdown = (
        "# 账号登录\n\n"
        "## 错误码\n\n"
        "| code | meaning |\n"
        "| --- | --- |\n"
        "| 401 | token 过期 |\n"
        "| 403 | 权限不足 |\n"
    )
    chunks = asyncio.get_event_loop().run_until_complete(MarkdownParser().parse(markdown, {"doc_id": "m"}))

    tables = [chunk for chunk in chunks if chunk.metadata.category == "table"]
    assert len(tables) == 1
    assert "| 401 | token 过期 |" in tables[0].content
    assert tables[0].metadata.heading_path == ["账号登录", "错误码"]
    assert tables[0].metadata.extra["is_atomic"] is True


def test_markdown_parser_keeps_fenced_code_block() -> None:
    import asyncio

    from app.parser.markdown_parser import MarkdownParser

    markdown = "# 排查\n\n```bash\ncurl -I https://example.com\n```\n"
    chunks = asyncio.get_event_loop().run_until_complete(MarkdownParser().parse(markdown, {"doc_id": "m"}))

    code_blocks = [chunk for chunk in chunks if chunk.metadata.category == "code"]
    assert len(code_blocks) == 1
    assert code_blocks[0].content == "```bash\ncurl -I https://example.com\n```"
    assert code_blocks[0].metadata.extra["language"] == "bash"


def test_get_parser_factory_dispatches_by_extension() -> None:
    from app.parser.base import get_parser

    assert get_parser("pdf").file_type == "pdf"
    assert get_parser("md").file_type == "md"
    assert get_parser("txt").file_type == "txt"


def test_get_parser_factory_rejects_unknown() -> None:
    from app.core.exceptions import UnsupportedFormat
    from app.parser.base import get_parser

    with pytest.raises(UnsupportedFormat):
        get_parser("docx")


def test_detect_file_type_falls_back_to_filename() -> None:
    from app.parser.base import detect_file_type

    assert detect_file_type("report.pdf", None) == "pdf"
    assert detect_file_type("notes.md", None) == "md"
    assert detect_file_type(None, "application/pdf") == "pdf"


@pytest.mark.parametrize("missing", [None, ""])
def test_parse_with_degradation_handles_empty_input(missing: Any) -> None:
    import asyncio

    from app.parser.base import parse_with_degradation

    chunks, warning = asyncio.get_event_loop().run_until_complete(
        parse_with_degradation("txt", missing or "", {"doc_id": "x"})
    )
    assert chunks == []
    assert warning is None
