"""MinerU content_list_v2 类型常量字典。

来源：airQA 项目 src/chunking/constants.py（用户自己的实现，借鉴复用）。
覆盖 MinerU 服务端返回的 BlockType + ContentTypeV2 + span 级类型。
"""

from __future__ import annotations

# ============================================================================
# chunk category（quillrag 内部统一分类，与 ChunkMetadata.category 对齐）
# ============================================================================
CATEGORY_TITLE = "title"
CATEGORY_PARAGRAPH = "paragraph"
CATEGORY_TABLE = "table"
CATEGORY_FORMULA = "formula"
CATEGORY_FIGURE = "figure"
CATEGORY_LIST_ITEM = "list_item"
CATEGORY_HEADER = "header"
CATEGORY_FOOTER = "footer"
CATEGORY_CODE = "code"

# ============================================================================
# MinerU 块级类型（BlockType + ContentTypeV2 顶层）
# ============================================================================

# 文本类
TYPE_TITLE = "title"
TYPE_PARAGRAPH = "paragraph"
TYPE_LIST = "list"
TYPE_PAGE_ASIDE_TEXT = "page_aside_text"
TYPE_PAGE_FOOTNOTE = "page_footnote"
TYPE_FOOTNOTE = "footnote"
TYPE_PAGE_HEADER = "page_header"
TYPE_PAGE_FOOTER = "page_footer"
TYPE_REF_TEXT = "ref_text"
TYPE_ABSTRACT = "abstract"
TYPE_DOC_TITLE = "doc_title"
TYPE_PARAGRAPH_TITLE = "paragraph_title"
TYPE_VERTICAL_TEXT = "vertical_text"
TYPE_PHONETIC = "phonetic"
TYPE_INDEX = "index"
TYPE_CODE = "code"
TYPE_CODE_BODY = "code_body"
TYPE_ALGORITHM = "algorithm"
TYPE_TEXT_LIST = "text_list"
TYPE_REFERENCE_LIST = "reference_list"

# 表格类
TYPE_TABLE = "table"
TYPE_CHART = "chart"
TYPE_TABLE_BODY = "table_body"
TYPE_CHART_BODY = "chart_body"
TYPE_SIMPLE_TABLE = "simple_table"
TYPE_COMPLEX_TABLE = "complex_table"

# 公式类
TYPE_EQUATION_INTERLINE = "equation_interline"
TYPE_INTERLINE_EQUATION = "interline_equation"
TYPE_EQUATION = "equation"
TYPE_EQUATION_INLINE = "equation_inline"
TYPE_FORMULA_NUMBER = "formula_number"

# 图像类
TYPE_IMAGE = "image"
TYPE_IMAGE_BODY = "image_body"
TYPE_SEAL = "seal"
TYPE_HEADER_IMAGE = "header_image"
TYPE_FOOTER_IMAGE = "footer_image"

# 标题/编号类
TYPE_PAGE_NUMBER = "page_number"
TYPE_IMAGE_CAPTION = "image_caption"
TYPE_TABLE_CAPTION = "table_caption"
TYPE_CHART_CAPTION = "chart_caption"
TYPE_ALGORITHM_CAPTION = "algorithm_caption"
TYPE_CODE_CAPTION = "code_caption"
TYPE_CAPTION = "caption"

# 其他
TYPE_DISCARDED = "discarded"
TYPE_CODE_FOOTNOTE = "code_footnote"
TYPE_IMAGE_FOOTNOTE = "image_footnote"
TYPE_TABLE_FOOTNOTE = "table_footnote"
TYPE_CHART_FOOTNOTE = "chart_footnote"

# ============================================================================
# span 级别类型（嵌入在 paragraph/title 等块内部）
# ============================================================================
SPAN_TYPE_TEXT = "text"
SPAN_TYPE_EQUATION_INLINE = "equation_inline"
SPAN_TYPE_INLINE_EQUATION = "inline_equation"
SPAN_TYPE_PHONETIC = "phonetic"
SPAN_TYPE_MD = "md"
SPAN_TYPE_CODE_INLINE = "code_inline"

KEEP_SPAN_TYPES = {
    SPAN_TYPE_TEXT,
    SPAN_TYPE_EQUATION_INLINE,
    SPAN_TYPE_INLINE_EQUATION,
    SPAN_TYPE_PHONETIC,
    SPAN_TYPE_MD,
    SPAN_TYPE_CODE_INLINE,
}

# ============================================================================
# MinerU 类型 → quillrag category 映射
# ============================================================================
TYPE_TO_CATEGORY: dict[str, str] = {
    # 标题
    TYPE_DOC_TITLE: CATEGORY_TITLE,
    TYPE_TITLE: CATEGORY_TITLE,
    TYPE_PARAGRAPH_TITLE: CATEGORY_TITLE,
    # 段落
    TYPE_PARAGRAPH: CATEGORY_PARAGRAPH,
    TYPE_ABSTRACT: CATEGORY_PARAGRAPH,
    TYPE_REF_TEXT: CATEGORY_PARAGRAPH,
    TYPE_PAGE_ASIDE_TEXT: CATEGORY_PARAGRAPH,
    TYPE_FOOTNOTE: CATEGORY_PARAGRAPH,
    TYPE_PAGE_FOOTNOTE: CATEGORY_PARAGRAPH,
    TYPE_INDEX: CATEGORY_PARAGRAPH,
    # 列表
    TYPE_LIST: CATEGORY_LIST_ITEM,
    TYPE_TEXT_LIST: CATEGORY_LIST_ITEM,
    TYPE_REFERENCE_LIST: CATEGORY_LIST_ITEM,
    # 表格
    TYPE_TABLE: CATEGORY_TABLE,
    TYPE_TABLE_BODY: CATEGORY_TABLE,
    TYPE_SIMPLE_TABLE: CATEGORY_TABLE,
    TYPE_COMPLEX_TABLE: CATEGORY_TABLE,
    TYPE_CHART: CATEGORY_TABLE,
    TYPE_CHART_BODY: CATEGORY_TABLE,
    # 公式
    TYPE_EQUATION_INTERLINE: CATEGORY_FORMULA,
    TYPE_INTERLINE_EQUATION: CATEGORY_FORMULA,
    TYPE_EQUATION: CATEGORY_FORMULA,
    # 图像
    TYPE_IMAGE: CATEGORY_FIGURE,
    TYPE_IMAGE_BODY: CATEGORY_FIGURE,
    TYPE_SEAL: CATEGORY_FIGURE,
    # 代码
    TYPE_CODE: CATEGORY_CODE,
    TYPE_CODE_BODY: CATEGORY_CODE,
    TYPE_ALGORITHM: CATEGORY_CODE,
    # 页眉页脚
    TYPE_PAGE_HEADER: CATEGORY_HEADER,
    TYPE_PAGE_FOOTER: CATEGORY_FOOTER,
}

# 应忽略的块类型（不产出 chunk）
IGNORE_TYPES: set[str] = {
    TYPE_PAGE_NUMBER,
    TYPE_DISCARDED,
    TYPE_IMAGE_CAPTION,
    TYPE_TABLE_CAPTION,
    TYPE_CHART_CAPTION,
    TYPE_ALGORITHM_CAPTION,
    TYPE_CODE_CAPTION,
    TYPE_CAPTION,
    TYPE_HEADER_IMAGE,
    TYPE_FOOTER_IMAGE,
    TYPE_FORMULA_NUMBER,
    TYPE_CODE_FOOTNOTE,
    TYPE_IMAGE_FOOTNOTE,
    TYPE_TABLE_FOOTNOTE,
    TYPE_CHART_FOOTNOTE,
}


def map_type_to_category(mineru_type: str | None) -> str | None:
    """返回内部 category；若应忽略则返回 None。"""
    if not mineru_type:
        return None
    if mineru_type in IGNORE_TYPES:
        return None
    return TYPE_TO_CATEGORY.get(mineru_type, CATEGORY_PARAGRAPH)


__all__ = [
    "CATEGORY_CODE",
    "CATEGORY_FIGURE",
    "CATEGORY_FOOTER",
    "CATEGORY_FORMULA",
    "CATEGORY_HEADER",
    "CATEGORY_LIST_ITEM",
    "CATEGORY_PARAGRAPH",
    "CATEGORY_TABLE",
    "CATEGORY_TITLE",
    "IGNORE_TYPES",
    "KEEP_SPAN_TYPES",
    "TYPE_TO_CATEGORY",
    "map_type_to_category",
]
