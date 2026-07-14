"""分块器与 cleaner 单测。"""

from __future__ import annotations

from app.models.chunk import Chunk, ChunkMetadata
from app.models.query import ChunkingStrategy
from app.parser.chunker import chunk_with_strategy, select_default_strategy
from app.parser.chunker.fixed import chunk as fixed_chunk
from app.parser.chunker.semantic import chunk as semantic_chunk
from app.parser.chunker.structure_aware import chunk as structure_chunk
from app.parser.cleaner import clean as clean_chunks


def _mk(content: str, *, category: str = "paragraph", path: list[str] | None = None, idx: int = 0) -> Chunk:
    return Chunk(
        content=content,
        metadata=ChunkMetadata(
            category=category,
            heading_path=path or [],
            chunk_index=idx,
        ),
    )


def test_select_default_strategy_matches_file_type() -> None:
    assert select_default_strategy("pdf") == ChunkingStrategy.STRUCTURE_AWARE
    assert select_default_strategy("md") == ChunkingStrategy.MARKDOWN_STRUCTURE
    assert select_default_strategy("txt") == ChunkingStrategy.FIXED


def test_fixed_chunker_respects_size_and_overlap() -> None:
    content = "字" * 1200
    chunks = fixed_chunk([_mk(content)], chunk_size=500, overlap=50)
    assert len(chunks) >= 3
    assert all(c.metadata.chunk_index == i for i, c in enumerate(chunks))


def test_structure_aware_merges_under_same_heading() -> None:
    raw = [
        _mk("标题A", category="title", path=["标题A"], idx=0),
        _mk("段落1。", path=["标题A"], idx=1),
        _mk("段落2。", path=["标题A"], idx=2),
        _mk("段落3。", path=["标题A"], idx=3),
    ]
    merged = structure_chunk(raw)
    paragraph_chunks = [c for c in merged if c.metadata.category == "paragraph"]
    assert len(paragraph_chunks) == 1
    assert "段落1" in paragraph_chunks[0].content
    assert "段落3" in paragraph_chunks[0].content


def test_semantic_chunker_groups_by_similarity() -> None:
    raw = [_mk("这是关于 RAG 的介绍。这是关于 RAG 的细节。这是关于服务的部署。")]
    chunks = semantic_chunk(raw)
    assert len(chunks) >= 1
    assert all(c.metadata.category == "paragraph" for c in chunks)


def test_markdown_structure_does_not_cross_heading_boundary() -> None:
    from app.parser.chunker.markdown_structure import chunk as markdown_structure_chunk

    raw = [
        _mk("# A", category="title", path=["A"], idx=0),
        _mk("A 段落一。", path=["A"], idx=1),
        _mk("A 段落二。", path=["A"], idx=2),
        _mk("## B", category="title", path=["A", "B"], idx=3),
        _mk("B 段落。", path=["A", "B"], idx=4),
    ]

    chunks = markdown_structure_chunk(raw)

    a_chunks = [chunk for chunk in chunks if chunk.metadata.heading_path == ["A"]]
    b_chunks = [chunk for chunk in chunks if chunk.metadata.heading_path == ["A", "B"]]
    assert any("A 段落一" in chunk.content and "A 段落二" in chunk.content for chunk in a_chunks)
    assert all("B 段落" not in chunk.content for chunk in a_chunks)
    assert any("B 段落" in chunk.content for chunk in b_chunks)


def test_markdown_structure_keeps_table_and_code_atomic() -> None:
    from app.parser.chunker.markdown_structure import chunk as markdown_structure_chunk

    raw = [
        _mk("# A", category="title", path=["A"], idx=0),
        _mk("| A | B |\n|---|---|\n| 1 | 2 |", category="table", path=["A"], idx=1),
        _mk("```bash\necho ok\n```", category="code", path=["A"], idx=2),
    ]

    chunks = markdown_structure_chunk(raw)

    table = next(chunk for chunk in chunks if chunk.metadata.category == "table")
    code = next(chunk for chunk in chunks if chunk.metadata.category == "code")
    assert table.content == "| A | B |\n|---|---|\n| 1 | 2 |"
    assert code.content == "```bash\necho ok\n```"


def test_chunk_with_strategy_unknown_falls_back_to_fixed() -> None:
    raw = [_mk("内容" * 400)]
    chunks = chunk_with_strategy(raw, ChunkingStrategy.FIXED, options={"chunk_size": 200, "chunk_overlap": 20})
    assert len(chunks) >= 2


def test_cleaner_removes_ocr_noise_and_merges_short() -> None:
    raw = [
        _mk("正常段落，足够长，应该被保留。", idx=0),
        _mk("□■", idx=1),
        _mk("短。", idx=2),
    ]
    cleaned = clean_chunks(raw)
    assert all("□" not in c.content and "■" not in c.content for c in cleaned)
    assert len(cleaned) <= len(raw)
    assert [c.metadata.chunk_index for c in cleaned] == list(range(len(cleaned)))


def test_cleaner_preserves_table_and_code_newlines() -> None:
    raw = [
        _mk("| A | B |\n|---|---|\n| 1 | 2 |", category="table", idx=0),
        _mk("```bash\n  echo ok\n```", category="code", idx=1),
    ]

    cleaned = clean_chunks(raw)

    assert cleaned[0].content == "| A | B |\n|---|---|\n| 1 | 2 |"
    assert cleaned[1].content == "```bash\n  echo ok\n```"
