# QuillRAG Markdown 分块优化预设方案

## 背景

当前 Markdown 入库链路是：

```text
MarkdownParser
  -> semantic chunker
  -> cleaner
```

这个默认链路适合普通叙述文本，但对 Markdown 的结构语义保护不足：

- `title` chunk 会在 semantic 阶段被排除，最终 chunk 容易丢失标题文本。
- Markdown 表格没有被识别为独立 `table` 元素，默认会被当作普通正文按换行拆句。
- 代码块虽然在 parser 中用 fence 保留，但后续 semantic 阶段仍可能把它和正文一起重组。
- 列表、步骤、告警块、FAQ 问答等结构没有稳定的原子边界。

本方案目标是把 Markdown 分块从“文本切分优先”调整为“结构保护优先，长度控制其次，语义切分只在安全边界内使用”。

## 外部成熟实践参考

### LangChain：按标题切分并保留 header metadata

LangChain 的 `MarkdownHeaderTextSplitter` 明确面向 Markdown 标题结构切分，按指定 header 生成 chunk，并把标题层级保存到 metadata。官方文档也提示默认会把标题从正文中移除，但 metadata 仍保留，可以通过参数关闭标题剥离。

参考：[LangChain MarkdownHeaderTextSplitter](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter)、[LangChain API Reference](https://reference.langchain.com/python/langchain-text-splitters/markdown/MarkdownHeaderTextSplitter)

对 QuillRAG 的启发：

- 标题层级应该是 Markdown 分块的一等信息。
- 标题既要写入 `heading_path`，也建议以可检索前缀形式进入 chunk content。
- 只把标题放 metadata 会影响向量相似度，因为大多数向量库不会把 metadata 参与正文 embedding。

### Haystack：标题切分后可选二级切分

Haystack 的 `MarkdownHeaderSplitter` 先按 ATX 标题切分，并保存 header hierarchy metadata；如果标题块过长，再用 secondary split 做二级切分。二级切分可以按 word、passage、period 或 line 执行。

参考：[Haystack MarkdownHeaderSplitter](https://docs.haystack.deepset.ai/docs/markdownheadersplitter)、[Haystack DocumentSplitter](https://docs.haystack.deepset.ai/docs/documentsplitter)

对 QuillRAG 的启发：

- Markdown 的第一层边界应该来自标题和结构块，不应该先做全局句子切分。
- 二级切分只应该发生在单个 section 内，不能跨标题合并。
- 二级切分需要继承 parent headers、source、split id 等 metadata。

### Unstructured：by_title 保留章节边界，表格是独立元素

Unstructured 的 chunking 文档强调 `by_title` 会保留 section boundary：新标题开始时关闭旧 chunk，避免一个 chunk 混入两个 section。它还区分 `CompositeElement` 和 `Table`，文本组合 chunk 不包含表格元素。配置上提供 `max_characters` 硬上限、`new_after_n_chars` 软上限、`combine_under_n_chars` 小块合并、`overlap` 等参数。

参考：[Unstructured Chunking](https://docs.unstructured.io/open-source/core-functionality/chunking)、[Unstructured Chunking Concepts](https://docs.unstructured.io/concepts/chunking)、[Unstructured API Parameters](https://docs.unstructured.io/api-reference/legacy-api/partition/api-parameters)

对 QuillRAG 的启发：

- 表格、代码块、图片说明、公式等应该是特殊元素，不应混进普通段落合并。
- 长度上限可以存在，但应优先对超长元素做专门处理，而不是无差别硬切。
- `combine_under_n_chars` 能缓解标题过密导致的小 chunk 问题。

### LlamaIndex：MarkdownNodeParser 与 MarkdownElementNodeParser

LlamaIndex 的 `MarkdownNodeParser` 按 Markdown header 逻辑切分，并在 node 中保留 header path；`MarkdownElementNodeParser` 更进一步，把表格等 embedded objects 拆成对应节点。

参考：[LlamaIndex MarkdownNodeParser](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/markdown/)、[LlamaIndex MarkdownElementNodeParser](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/markdown_element/)

对 QuillRAG 的启发：

- 可以分两层：section node 用于正文，element node 用于表格、代码、列表等结构化对象。
- 表格这类对象需要独立索引，同时保留其所在标题路径。
- prev/next 关系对 Markdown 文档同样有价值，尤其是流程步骤和 FAQ。

### Semantic split：只能作为 section 内的二级策略

LlamaIndex 的 semantic splitter 思路是用 embedding 相似度在句子之间寻找断点。这个策略适合长篇自然语言，但不适合直接作用于完整 Markdown 文档，否则会破坏标题、表格、代码块和列表结构。

参考：[LlamaIndex Semantic Chunker](https://developers.llamaindex.ai/python/examples/node_parsers/semantic_chunking/)、[SemanticSplitterNodeParser](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/semantic_splitter/)

对 QuillRAG 的启发：

- 语义切分可以保留，但应限定在普通 paragraph section 内。
- 对 table、code、list、blockquote、frontmatter 等结构元素禁用语义重组。
- 语义切分输出必须继承当前 section 的标题路径。

## 目标

- Markdown 表格默认不被拆行，不跨 chunk 截断。
- fenced code block 默认不被拆开。
- 标题层级稳定进入 `heading_path`，并可选进入 chunk content。
- 同一 chunk 不跨越不同标题章节。
- 普通段落过长时才二级切分，优先按段落、句子、列表项等自然边界。
- chunk metadata 能表达 `category`、`heading_path`、`element_type`、`parent_id`、`prev_view_id`、`next_view_id`。
- 现有 `/parse`、`/ingest` 的 `strategy` 参数保持兼容。

## 非目标

- 不引入 LLM 做默认分块。
- 不把假设问题、关键词扩写直接写回原始 Markdown 正文。
- 不为了当前评测集硬编码业务词。
- 不一次性重写 PDF/MinerU 分块链路。

## 推荐默认策略

建议把 Markdown 默认策略从当前 `semantic` 调整为：

```text
markdown_structure_v1
```

核心流程：

```text
Markdown source
  -> block parser
  -> structural elements
  -> section-aware grouping
  -> safe secondary split
  -> cleaner
  -> reindex + neighbor links
```

其中：

- `block parser` 识别 heading、paragraph、table、list、code、blockquote、hr、html block。
- `section-aware grouping` 按标题路径聚合普通正文，不跨 section。
- `safe secondary split` 只处理超长 paragraph/list section，不处理 table/code。
- `cleaner` 不应把 table/code 内部换行强行变成空格。

## 分块预设

### 预设 A：`markdown_safe`

面向表格、代码、配置、API 文档、运维手册。

```yaml
name: markdown_safe
section_boundary: heading
keep_headers_in_content: true
atomic_blocks:
  - table
  - fenced_code
  - html_block
  - math_block
  - list
max_chars: 1200
soft_chars: 800
combine_under_chars: 120
secondary_split:
  paragraph: sentence
  list: item
  table: none
  fenced_code: none
overlap: 0
```

行为说明：

- 表格整张作为 `category=table`，不按行拆。
- 代码块整段作为 `category=code`，保留换行和语言标识。
- 列表默认作为一个 list block；超过上限时按 list item 切。
- 小标题下只有很短内容时，可以合并到同 section 的下一个普通文本 chunk，但不能跨父标题。

适合作为 Markdown 的新默认预设。

### 预设 B：`markdown_balanced`

面向一般知识库说明文，兼顾结构和召回粒度。

```yaml
name: markdown_balanced
section_boundary: heading
keep_headers_in_content: true
atomic_blocks:
  - table
  - fenced_code
  - math_block
max_chars: 1000
soft_chars: 650
combine_under_chars: 160
secondary_split:
  paragraph: semantic_sentence
  list: item
  table: none
  fenced_code: none
overlap: 80
overlap_scope: only_oversized_text
```

行为说明：

- 对普通段落可以使用现有 semantic 思路，但只能在同一 section 内执行。
- overlap 只用于被迫切开的长文本，不给正常结构块加 overlap。
- 输出 chunk 仍继承完整 `heading_path`。

适合内容以解释性段落为主、表格不多的文档。

### 预设 C：`markdown_retrieval_plus`

面向检索质量实验，支持父子 chunk 和多视图索引。

```yaml
name: markdown_retrieval_plus
base: markdown_safe
child_chunks:
  enabled: true
  child_max_chars: 350
  child_split: sentence
parent_context:
  enabled: true
  parent_max_chars: 1200
multi_view:
  title_prefixed_text: true
  table_summary: optional
  code_signature: optional
```

行为说明：

- parent chunk 保留完整 section 或原子元素，用于回答上下文。
- child chunk 更小，用于召回。
- 命中 child 后返回 parent 或邻居窗口。
- `table_summary` 和 `code_signature` 若启用，必须作为派生 metadata 或额外检索视图，不能污染原文。

适合后续评测优化，不建议第一阶段直接作为默认。

## 元数据规范

建议 Markdown chunk 至少包含：

```json
{
  "category": "paragraph|title|table|list|code|blockquote",
  "heading_path": ["一级标题", "二级标题"],
  "chunk_index": 0,
  "doc_id": "...",
  "extra": {
    "element_type": "markdown_table",
    "header_level": 2,
    "parent_id": "doc:section:3",
    "chunk_id": "doc:12",
    "prev_view_id": "doc:11",
    "next_view_id": "doc:13",
    "is_atomic": true,
    "split_reason": "section|oversized|table|code|list"
  }
}
```

标题建议同时进入 content：

```text
# 一级标题
## 二级标题

正文内容...
```

原因：标题通常包含关键实体和主题词，只放在 metadata 中会削弱向量召回。

## 表格处理规则

Markdown 表格识别规则：

```text
| col_a | col_b |
| --- | --- |
| a | b |
```

当连续行满足以下条件时识别为表格：

- 至少 2 行。
- 第二行是 Markdown separator 行。
- 表格行包含 `|`。
- 前后空行或 block 边界结束表格。

表格 chunk 行为：

- 默认整张表作为一个 chunk。
- `category=table`。
- 保留原始 Markdown 表格文本。
- `extra.table_rows`、`extra.table_cols` 可选。
- 超长表格不按字符截断，优先按表头重复的 row group 切分。

超长表格切分示例：

```text
chunk 1:
| A | B |
|---|---|
| r1 | ... |
| r2 | ... |

chunk 2:
| A | B |
|---|---|
| r3 | ... |
| r4 | ... |
```

这样每个子表仍是合法 Markdown 表格。

## 代码块处理规则

fenced code block 识别规则：

````text
```python
print("hello")
```
````

代码块 chunk 行为：

- 默认整段作为 `category=code`。
- 保留语言标识和换行。
- cleaner 不压平代码内部换行。
- 超长代码块优先按函数、类、空行切；无法识别时才按行切。
- 切分后的每个 code chunk 都必须补齐 fence，避免 Markdown 语义破损。

## 列表处理规则

列表包括：

- 无序列表：`-`、`*`、`+`
- 有序列表：`1.`
- 任务列表：`- [ ]`、`- [x]`

默认行为：

- 连续列表作为 `category=list`。
- 保留缩进，避免破坏嵌套层级。
- 短列表不拆。
- 超长列表按顶层 item 切分。
- 切分时不能把一个嵌套子列表拆离父 item。

## Cleaner 调整

当前 cleaner 会把所有换行压成空格：

```python
text = _NEWLINE_RE.sub(" ", text)
```

Markdown 优化后需要按 category 区分：

- `paragraph`：可以压平普通换行。
- `table`：保留换行。
- `code`：保留换行和缩进。
- `list`：保留换行和缩进。
- `blockquote`：保留换行，必要时去除多余空行。

否则即使 parser 正确识别表格和代码，cleaner 仍会破坏它们。

## 与现有策略的兼容

保留现有枚举：

```text
fixed
semantic
structure_aware
```

新增建议：

```text
markdown_structure
```

默认策略调整：

```python
if normalized in {"md", "markdown"}:
    return ChunkingStrategy.MARKDOWN_STRUCTURE
```

兼容策略：

- 用户显式传 `strategy=semantic` 时，仍走旧 semantic。
- 用户显式传 `strategy=fixed` 时，仍走固定窗口。
- `markdown_structure` 可以接收 `preset=markdown_safe|markdown_balanced|markdown_retrieval_plus`。
- 如果暂时不扩展 API，可先用配置项 `DEFAULT_MARKDOWN_PRESET=markdown_safe`。

## 实施路线

### 阶段一：结构 parser 增强

- 在 `app/parser/markdown_parser.py` 中识别 table、fenced code、list、blockquote。
- 输出更细的 `category`。
- 给 `extra` 写入 `element_type`、`is_atomic`、`split_reason`。
- 保持当前 `Chunk` 模型兼容，不新增数据库字段。

### 阶段二：新增 Markdown 结构分块器

- 新增 `app/parser/chunker/markdown_structure.py`。
- 按 section 聚合普通文本。
- 对 table/code/list 使用原子块规则。
- 对超长普通文本做安全二级切分。
- 给 chunk 生成连续 `chunk_index`。

### 阶段三：Cleaner 按 category 清洗

- 修改 `app/parser/cleaner.py`。
- 对 table/code/list 禁止压平换行。
- 短块合并只合并普通 paragraph，且必须同一 `heading_path`。

### 阶段四：默认策略灰度切换

- 先在测试里显式调用 `markdown_structure`。
- 再通过配置开关控制 Markdown 默认策略。
- 最后将 `.md/.markdown` 默认从 `semantic` 切到 `markdown_structure`。

### 阶段五：评测与回归

- 新增 Markdown fixture，覆盖标题、表格、代码、列表、FAQ。
- 对比旧 `semantic` 和新 `markdown_safe` 的 chunk 数、平均长度、召回指标。
- 重点检查表格和代码是否被 cleaner 破坏。

## 测试清单

必须新增或更新以下测试：

- `test_markdown_parser_extracts_tables_as_atomic_chunks`
- `test_markdown_parser_keeps_fenced_code_block`
- `test_markdown_structure_does_not_cross_heading_boundary`
- `test_markdown_structure_repeats_table_header_when_splitting_large_table`
- `test_cleaner_preserves_table_newlines`
- `test_cleaner_preserves_code_indentation`
- `test_markdown_default_strategy_can_be_configured`

验收样例：

````markdown
# 账号登录

## 错误码

| code | meaning |
| --- | --- |
| 401 | token 过期 |
| 403 | 权限不足 |

## 排查脚本

```bash
curl -I https://example.com
```
````

期望：

- 表格是一个完整 `table` chunk。
- bash 代码是一个完整 `code` chunk。
- 表格 chunk 的 `heading_path` 是 `["账号登录", "错误码"]`。
- 代码 chunk 的 `heading_path` 是 `["账号登录", "排查脚本"]`。
- cleaner 后表格仍然多行，代码仍然多行。

## 风险与取舍

- 结构保护会让部分 chunk 比旧 semantic 更长，需要通过 `soft_chars` 和二级切分控制。
- 标题进入 content 会略微增加 token，但通常利于召回。
- 表格整张保留可能导致超长 chunk，因此需要 row group 切分，而不是简单硬切。
- 新策略会改变 chunk_index，已有 golden set 和已入库 collection 需要重新生成或迁移。

## 推荐决策

第一阶段建议采用：

```yaml
default_markdown_preset: markdown_safe
enable_markdown_structure_strategy: true
keep_headers_in_content: true
preserve_table_newlines: true
preserve_code_newlines: true
```

原因：

- 它最直接解决当前问题：表格和段落被截断。
- 不依赖新模型和 LLM。
- 与现有 `Chunk` / `ChunkMetadata` 兼容。
- 后续可以在此基础上增加 `markdown_balanced` 和父子 chunk 检索。

## 成功标准

- Markdown 表格不会在默认策略中被按换行拆散。
- fenced code block 不会被 cleaner 压成一行。
- 同一 chunk 不跨越两个不同标题章节。
- 新旧策略在 `/parse` 可对比。
- `tests/parser` 全部通过。
- 至少一份 Markdown golden set 重新评测后，`Recall@5` 不低于旧策略，表格相关 query 的命中率提升。
