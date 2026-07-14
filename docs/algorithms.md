# 算法与流程解析

本文档描述 QuillRAG 的核心算法与数据流。先看宏观架构,再逐层拆解入库与召回两条主链路,最后单独讲清每个关键算法的设计动机与实现细节。

---

## 1. 项目定位

QuillRAG 是一个独立部署的检索增强生成(RAG)的**检索侧服务**。它只负责"解析 → 入库 → 检索 → 重排"四件事,不包含 LLM 生成。设计目标:

- 作为 sidecar 部署在 LLM 应用旁边,通过 HTTP 调用
- 处理学术 PDF 的复杂版面(表格、公式、双栏、图表)
- 混合检索 + Cross-Encoder 精排,提供生产级召回质量
- 全链路降级,单点故障不让主系统跟着挂

---

## 2. 整体架构

```
                    HTTP 请求
                       │
        ┌──────────────▼──────────────┐
        │  Middleware 层               │
        │  RequestLogging → Auth       │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  API 层(FastAPI Router)      │
        │  /parse /ingest /retrieve    │
        │  /rerank /collections /health│
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Services 层(编排)           │
        │  parse / ingest / retrieve   │
        │  / rerank / collection       │
        └─────┬───────┬────────┬───────┘
              │       │        │
       ┌──────▼┐  ┌──▼──┐  ┌──▼────────┐
       │parser │  │retrieval│ storage   │
       │       │  │       │ │           │
       │• MinerU│ │• dense│ │• Qdrant   │
       │• PyMuPDF││• sparse│ │• SQLite   │
       │• chunker││• hybrid│ │  metadata │
       │• cleaner│ │• rerank│ │• version  │
       │       │  │• hyde │ │• collection│
       └───────┘  └───────┘ └───────────┘
```

### 模块职责边界

| 层 | 职责 | 关键约束 |
|---|---|---|
| `app/api/` | HTTP 入参出参,不做业务 | 只做参数校验、调 service、包 ApiResponse |
| `app/services/` | 编排多个底层模块 | 业务流程在这,不直接操作 Qdrant |
| `app/parser/` | 文件 → 结构化 Chunk | 不写库,只产出 Chunk 列表 |
| `app/retrieval/` | 召回、融合、重排 | 不持久化,纯计算 |
| `app/storage/` | Qdrant + SQLite 操作 | 只做存取,不含业务规则 |
| `app/models/` | Pydantic 数据模型 | 跨层传递的 DTO |

### 解析器与分块器分离

`parser` 只产生"碎片 chunks"(一个 layout element 对应一个 chunk),由 `chunker` 按策略做合并。这让 parser 不必关心分块策略,chunker 不必关心文件格式。

### Embedder / Reranker 懒加载

模型在首次调用时由后台线程加载,加载期间 `is_ready()=False`,`/health` 显示 `loading`。这避免服务启动阻塞 1-2 分钟(Cross-Encoder 模型可达 2GB)。

---

## 3. 入库流程(/ingest)

完整链路共 10 步:

```
PDF bytes
   │
   ▼
[1] MinerU 云端 API ── 失败 ──→ PyMuPDF 启发式 fallback
   │
   ▼
[2] JSON → Chunk 列表
   │   • map_type_to_category: 50+ block type → 5 类
   │   • 构建 heading_path(用 text_level 维护标题层级栈)
   │   • 表格 HTML → markdown + records(行式 key=value)
   │   • 公式 LaTeX → Unicode(latex_to_text,\alpha → α)
   ▼
[3] 语义锚点:对 table/formula/figure,用 bbox 中心点欧氏距离
   │   找"空间最近的标题"作为 heading_path
   ▼
[4] logic_idx + prev/next 邻居 ID
   │   • logic_idx: 跨页全局连续序号(还原阅读顺序)
   │   • prev_view_id/next_view_id: 同 category 邻居(用于扩窗)
   ▼
[5] Chunker 四选一(fixed / semantic / structure_aware / markdown_structure)
   │   PDF 默认 structure_aware；Markdown 默认 markdown_structure
   ▼
[6] 幂等检查: md5(content) + doc_id 查 SQLite
   │   • 已存在且 hash 相同 → return noop(省 embedding 成本)
   │   • 已存在但 hash 不同 → 先 delete 旧 Qdrant points
   ▼
[7] Embedder: chunks → 3072 维向量(Gemini/OpenAI,batch=64)
   ▼
[8] 同时构造 Sparse 向量(jieba 分词 → hash 到 uint32)
   ▼
[9] Qdrant upsert: 每个 chunk = 1 个 point
       point_id = uuid4
       vector  = { dense: [...3072], sparse: {indices, values} }
       payload = { content, doc_id, chunk_index, category,
                   heading_path, page, logic_idx, prev_view_id, ... }
   ▼
[10] SQLite documents 表 upsert + document_versions 表记版本
```

### 入库幂等性设计

```python
content_hash = md5(content)
doc_id       = compute_doc_id(content)   # 内容指纹
existing     = store.get_document(doc_id, collection)

if existing and existing.content_hash == content_hash:
    return {"action": "noop"}            # 完全相同,跳过

if existing:
    delete_document_points(collection, doc_id)   # 先删旧 chunk

write_to_qdrant(...)                     # 再写新 chunk
store.upsert_document(record)
version_manager.record_ingest(record, previous_hash=existing.content_hash)
```

三个工程要点:

1. **幂等**: 同一文档二次入库直接 noop,避免重复 embedding 消耗
2. **先删后写**: 删旧 point → 写新 point,避免出现"半个文档"中间态
3. **版本回溯**: 每次更新记 `previous_hash`,支持 diff 与回滚

---

## 4. 召回流程(/retrieve + /rerank)

完整链路共 8 步:

```
query string
   │
   ▼
[1] (可选) HyDE: LLM 生成假设性答案 → 用答案的向量去检索
   │
   ▼
[2] 并行双路召回:
   ├─ Dense:  query → embedder → 3072维向量 → Qdrant query_points
   │           score_threshold=0.3 过滤低相关
   └─ Sparse: query → jieba 分词 → hash → SparseVector → Qdrant query_points
              using=SPARSE_VECTOR_NAME
   │
   │   各自召回 top max(top_k*2, 20) 条
   ▼
[3] Hybrid 融合(hybrid_searcher.fuse)
   │   方案 A RRF:         score = Σ w_i / (k + rank_i)         ← 无量纲
   │   方案 B MinMax+加权:  先归一化再加权(默认,weights=0.7/0.3)
   ▼
[4] Diversity Penalty
   │   同 doc_id 多条: 第 n 条 score *= max(0.5, 1 - 0.1*(n-1))
   │   避免 top_k 全是同一篇文档
   ▼
[5] 截断 top_k
   ▼
[6] (可选) Jaccard 去重: 阈值 0.7,过滤高度相似 chunk
   │
   ▼
[7] (可选) Cross-Encoder Rerank /rerank
   │   从 top_k 中取 top_n,query+doc 拼一起过 Transformer
   │   输出精排 score,重新排序
   ▼
[8] 返回(可按 logic_idx 排序还原阅读顺序)
```

### 三级降级策略

| 故障点 | 行为 |
|---|---|
| Qdrant 不可用 | 抛 `QdrantUnavailable` → HTTP 503,主系统走"无 RAG"分支 |
| Embedder 不可用 | Dense 路跳过,只用 Sparse(BM25)召回,次优但可用 |
| Reranker 不可用 | 抛 `RerankerUnavailable` → `/rerank` 按原 score 排序返回 |

原则:**宁可次优也不要直接失败**。

---

## 5. 核心算法详解

### 5.1 MinerU 解析 + type 映射收敛

MinerU 返回的 `content_list_v2.json` 包含 50+ 种 block type。解析器用一个映射表收敛成 5 类:

| MinerU type | category |
|---|---|
| `text`, `paragraph` | `paragraph` |
| `title`(带 `text_level`) | `title` |
| `table`, `table_caption` | `table` |
| `equation_interline`, `equation_inline` | `formula` |
| `image`, `chart` | `figure` |
| 其他 40+ 未知类型 | `None`,丢弃 |

新增 type 只改映射表,不动下游逻辑。

### 5.2 语义锚点(给非文本 chunk 补可检索性)⭐

#### 问题本质

表格、公式、图片的 chunk 内容是 LaTeX 或 HTML,本身没有可检索的文本语义。比如公式 `$$E=mc^2$$` 搜"质能方程"是搜不到的——BM25 拿到的是 LaTeX 字符串,与中文问句零词重合。

#### 核心思想

给每个非文本 chunk **借一个"语义相关"的标题路径**,让它的 `heading_path` 字段带上所属章节,这样 BM25 搜章节名时也能命中。本质是把"非文本元素的上下文"通过最近的标题代理出来。

#### 当前实现:空间最近标题

代码位置:`app/parser/mineru/parser.py:_anchor_path_for`

```python
def _anchor_path_for(target_bbox, target_page, title_records, fallback):
    best = None
    for title in title_records:           # 遍历全文档标题(不是相邻节点)
        # 候选条件:同页或前 2 页 + 锚点 bbox 在 target 上方
        page_delta = target_page - title.page
        if page_delta < -1 or page_delta > 2: continue
        if same_page and title.bbox.y1 > target.bbox.y0: continue

        # 距离 = bbox 中心点欧氏距离
        distance = sqrt((rx-tx)² + (ry-ty)²)
        # 同页 ×0.5,跨页 ×(1 + 0.5*|page_delta|)
        weighted = distance * weight
        if weighted < best: best = weighted, title

    # 用胜出标题的 level 反向重建完整 heading_path
    return rebuild_path_to_level(best.title)
```

| 设计点 | 选择 | 原因 |
|---|---|---|
| 候选范围 | 全文档所有标题(加页面跨度约束) | 不是相邻节点,而是全局最优 |
| 距离度量 | bbox 中心点欧氏距离 | PDF 已有 bbox 坐标,零额外计算 |
| 方向约束 | 同页时锚点必须在 target 上方 | 标题天然在内容上方,过滤下方噪声 |
| 页面跨度 | 前 2 页 + 后 1 页 | 公式可能紧跟上一页末尾标题 |
| 跨页加权 | ×(1 + 0.5×Δpage) | 同页标题优先,跨页标题降权 |
| 输出 | 用胜出标题的 level 反向重建完整 heading_path | 不只取一个标题,而是还原整条路径 |

**效果**: 孤立公式 `$$\alpha$$` 的 metadata 会带上 `heading_path=["第三章", "3.2 系数定义"]`,BM25 搜"系数定义"即可命中。

#### 与"相邻节点"的区别

项目里其实有两个独立的"上下文"机制,容易混淆:

| 机制 | 触发对象 | 找的是 | 度量方式 | 用途 | 阶段 |
|---|---|---|---|---|---|
| **语义锚点** | table / formula / figure | 空间最近的标题 | bbox 物理距离 | 给非文本 chunk 补 `heading_path`,让 BM25 能命中 | 入库 |
| **prev/next 邻居** | 所有 chunk | 同 category 内 logic_idx 前后 | 逻辑顺序(无距离) | 检索阶段扩窗,补上下文 | 检索 |

#### 替代方案:embedding 语义匹配(airQA 思路)

airQA 项目里曾尝试过另一种思路:**不靠空间距离,而是用 embedding 余弦相似度找语义最像的标题**。

```python
# airQA 风格
target_vec = embed(target_caption_or_context)   # 公式所在段的上下文
best = max(titles, key=lambda t: cosine(embed(t.text), target_vec))
```

| 维度 | 空间距离(当前) | embedding 语义匹配(airQA) |
|---|---|---|
| 准确性(单栏) | ✅ 高 | ✅ 高 |
| 准确性(双栏) | ❌ 易跨栏错配 | ✅ 不受栏位影响 |
| 准确性(图表标题在下方) | ⚠️ 标题必须在上方,会漏 | ✅ 不受方向限制 |
| 入库开销 | O(n),纯坐标计算 | 多一次 title embedding 调用 |
| 外部依赖 | 无 | 依赖 Embedder 服务可用 |
| 调试难度 | 容易(画 bbox 可视化) | 难(语义相似度黑盒) |

#### embedding 方案的陷阱

纯 embedding 匹配有一个明显问题:**没有局部性约束,可能找到文档另一章的相似标题**。

例子:公式在"第三章 系统设计",但全文还有个标题叫"附录 A 系统设计补遗",语义相似度极高,embedding 会把锚点错误地指向附录。

airQA 那套做法通常会加一个**候选预筛**来缓解:

```python
# airQA 风格的两阶段
candidates = [t for t in titles if spatial_distance(t, target) < threshold]  # 先空间筛
best = max(candidates, key=lambda t: cosine(embed(t), embed(target)))        # 再语义挑
```

#### 推荐升级:三段式混合方案(见第 9 节扩展点)

```
1. 候选预筛: 同页或前 2 页的所有标题 (空间约束,~5-10 个候选)
2. 主排序:   embedding 余弦相似度 (语义匹配)
3. 兜底:     若候选为空或最高分 < 0.3,降级到纯空间距离
```

优势:

- 复用已入库的 title embedding(每个 title chunk 本来就有 dense 向量),**几乎零额外成本**
- 解决双栏跨栏错配
- 保留空间约束避免"附录章节"陷阱

### 5.3 LaTeX → Unicode 文本化

**问题**: BM25 搜"alpha" 命中不到 `\alpha`。

**算法**(`app/parser/mineru/latex_normalizer.py`):

```python
latex_to_text(r"\alpha + \beta^2") → "α + β²"
```

文本化结果写入 chunk 的 `extra.text`,并追加到 `content` 字符串末尾,让 BM25 能匹配。

### 5.4 表格序列化为 key=value 记录

**问题**: 表格 HTML 作为一个整体 chunk,BM25 无法按字段命中。

**算法**(`app/parser/mineru/table_normalizer.py`):

将 HTML 表格解析为 `records=[{"列名": "值", ...}, ...]`,序列化成 `key=value` 文本拼到 content。搜"化学式=H2O"可直接命中表格 chunk。

### 5.5 logic_idx + prev/next 邻居

**问题**: chunk 入库后顺序按 Qdrant point_id(uuid)随机,无法还原文档阅读顺序。

**算法**:

```python
# 1. 按 page + chunk_index 排序,赋全局连续 logic_idx
sorted_chunks = sorted(chunks, key=lambda c: (c.metadata.page, c.metadata.chunk_index))
for idx, c in enumerate(sorted_chunks):
    c.metadata.extra["logic_idx"] = idx

# 2. 同 category 内,基于 logic_idx 找前后邻居
# table 的 prev_table/next_table,formula 的 prev_formula/next_formula
```

**用途**:

- 检索返回后按 `logic_idx` 排序 → 还原阅读顺序
- 命中一条 chunk 后,可用 `next_view_id` 拉回下一条同类型 chunk(扩窗)

### 5.6 稀疏向量构造(Qdrant 原生 BM25)

#### 背景:为什么需要 Sparse 路

Dense(向量)是语义匹配但弱于精确关键词,Sparse(BM25)恰好相反——专有名词、错误码、人名、产品型号这类"字面一致才相关"的查询,BM25 显著优于向量。两路互补是混合检索的基础。

#### BM25 公式回顾

经典 BM25 公式:

```
score(q, d) = Σ_t  IDF(t) × (tf(t,d) × (k₁+1)) / (tf(t,d) + k₁×(1 - b + b×|d|/avgdl))
```

- `tf(t,d)`:词 t 在文档 d 中的词频
- `IDF(t)`:词 t 的逆文档频率(罕见词权重高)
- `|d| / avgdl`:文档长度归一化(短文档命中权重高)
- `k₁=1.2`, `b=0.75`:经验参数

**核心思想**:既考虑词频,又惩罚"在所有文档都常见的词"(IDF),还做文档长度归一化,避免长文档因"词汇量大"而虚高。这一套是 1994 年提出的经典算法,至今仍是工业界 sparse 检索的事实标准。

#### 当前实现

Qdrant 1.10+ 原生支持 sparse vector 索引,但客户端要自己分词构造 sparse vector。Qdrant 服务端用 BM25 公式打分。

代码位置:`app/retrieval/sparse_searcher.py:build_sparse_vector`

```python
def build_sparse_vector(text):
    tokens = jieba.lcut(text)                  # 中文分词
    counts = {}
    for tok in tokens:
        idx = abs(hash(tok)) % (2**31)         # hash 到 uint32
        counts[idx] = counts.get(idx, 0) + 1   # 词频作为 value
    return {"indices": sorted(counts), "values": [...]}
```

**职责划分**:

| 端 | 做什么 |
|---|---|
| 客户端(本服务) | 分词 + 词频统计 + hash 到 uint32 |
| Qdrant 服务端 | 索引阶段预计算 IDF 与文档长度,查询时套 BM25 公式打分 |

#### 为什么用 jieba 而不是字符级分词

- 字符级(逐字):粒度太细,BM25 的 IDF 失效("的""了"这种无意义单字被高估)
- jieba 词级:有词典和 HMM,分出的词有语义单位,IDF 才有意义

#### 为什么用 hash 而不是维护词表

- 维护词表需要额外存储 + 同步,且不同 collection 词表可能不同
- Qdrant 要求 sparse vector 的 index 是 uint32,hash 直接满足
- **代价**:hash 冲突(不同词 hash 到同一 index)会轻微降低精度,但 uint32 空间足够大,冲突概率可忽略

#### 降级机制

老 collection 未配 sparse index 时,客户端 `scroll` 拉全部 payload,做轻量词频匹配(`_fallback_payload_search`):

```python
def _term_score(query_tokens, content):
    content_tokens = tokenize(content)
    score = 0.0
    for token in query_tokens:
        if token in content_set:
            score += 1.0 + content_tokens.count(token) / len(content_tokens)
    return score
```

这是 BM25 的极简替代:命中加分 + 词频归一化,**牺牲 IDF 但保证可用**。让旧 collection 不需要重建索引也能跑 sparse 检索。

### 5.7 Hybrid 融合(RRF vs MinMax)⭐

#### 5.7.1 为什么需要融合

Dense 和 Sparse 召回回来的分数**根本不能直接相加**,因为两者分数量纲完全不同:

| 检索器 | 分数量纲 | 典型范围 | 解释 |
|---|---|---|---|
| Dense(余弦相似度) | [-1, 1] 或 [0, 1] | 0.7 ~ 0.95 | 越大越像 |
| Sparse(BM25) | 无界 | 0 ~ ∞(常见 5 ~ 30) | 词频 × IDF 累加 |

直接 `fused = 0.7*dense_score + 0.3*sparse_score` 会让 BM25 的 5 分瞬间把 dense 的 0.9 压没。

融合算法要解决的核心问题:**怎么把两个不可比的分数合到一个排序里**。项目内置两套方案。

#### 5.7.2 方案 A:RRF(Reciprocal Rank Fusion,倒数排名融合)

**核心思想(一句话)**

**别管分数,只看排名。把每个文档在每个检索器里的排名取倒数,加权求和。**

**公式**

```
RRF_score(d) = Σ_i  w_i / (k + rank_i(d))
```

- `d` = 文档,`i` = 第 i 个检索器
- `w_i` = 该检索器权重(如 dense 0.7 / sparse 0.3)
- `k` = 平滑常数(默认 60)
- `rank_i(d)` = 文档 d 在第 i 个检索器里的排名(从 1 开始)

**三个关键设计问题**

**Q1: 为什么用"倒数"?**

- 排名 1 贡献 1/(k+1),排名 100 贡献 1/(k+100)
- 倒数天然实现"高排名权重大、低排名权重小",符合直觉

**Q2: 为什么加 `k`?这个常数干嘛的?**

- 不加 k(即 `1/rank`): rank=1 是 1.0,rank=2 是 0.5,第一名影响力是第二名的两倍——过于激进
- 加 k=60: rank=1 vs rank=2 是 1/61 vs 1/62,差距不到 2%——平滑
- **k 越大**,越倾向"两个检索器都认可"的文档(共识派)
- **k 越小**,越倾向"某个检索器排第一"的文档(独狼派)

**Q3: 为什么是 60 不是 50 或 100?**

来自 [原论文 Cormack et al., 2009](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf),大规模 TREC 实验的经验最优值。工业界 ElasticSearch、OpenSearch、Vespa 都默认 60,30~100 都合理。

**一个具体例子**

查 "transformer 原理",两路各返回 5 条:

| 文档 | dense_score | dense_rank | sparse_score | sparse_rank |
|---|---|---|---|---|
| doc_A | 0.95 | 1 | 12.3 | 3 |
| doc_B | 0.89 | 2 | 18.7 | 1 |
| doc_C | 0.87 | 3 | 15.1 | 2 |
| doc_D | 0.85 | 4 | 4.2 | 8 |
| doc_E | 0.83 | 5 | 3.1 | 12 |

用 RRF(k=60, w_dense=0.7, w_sparse=0.3):

```
RRF(A) = 0.7/(60+1) + 0.3/(60+3)   = 0.01148 + 0.00476 = 0.01624
RRF(B) = 0.7/(60+2) + 0.3/(60+1)   = 0.01129 + 0.00492 = 0.01621
RRF(C) = 0.7/(60+3) + 0.3/(60+2)   = 0.01111 + 0.00484 = 0.01595
RRF(D) = 0.7/(60+4) + 0.3/(60+8)   = 0.01094 + 0.00441 = 0.01535
RRF(E) = 0.7/(60+5) + 0.3/(60+12)  = 0.01077 + 0.00417 = 0.01494
```

排序结果:A > B > C > D > E(B 的 sparse_rank=1 但总排名第二,因为 dense 权重高)。

**RRF 的优缺点**

| 优点 | 缺点 |
|---|---|
| ✅ 天然无量纲,不关心分数量纲 | ❌ 丢失绝对分数信息(rank=1 但 score 只有 0.5 看不出来) |
| ✅ 实现简单,只需排序结果 | ❌ 并列排名处理需要约定 |
| ✅ 对异常分数鲁棒(一个 9999 分不会主导) | ❌ 不知道"差一点没排上 top-k"的文档 |
| ✅ 工业主流,ES/OpenSearch 内置 | ❌ k 是全局常数,不能按查询动态调 |

#### 5.7.3 方案 B:MinMax 归一化 + 加权融合

**核心思想(一句话)**

**保留分数信息,但先把两路分数各自压到 [0, 1] 同一区间,再加权求和。**

**两步公式**

**Step 1:MinMax 归一化** —— 把每路分数压到 [0, 1]

```
score_norm(d) = (score(d) - min) / (max - min)
```

- 最高分 → 1.0
- 最低分 → 0.0
- 中间分 → 线性映射

**Step 2:加权求和**

```
fused(d) = w_dense × dense_norm(d) + w_sparse × sparse_norm(d)
```

权重 0.7/0.3 的语义非常明确:**70% 信语义,30% 信关键词**。

**三个关键设计问题**

**Q1: 为什么用 MinMax 而不是 Z-Score(标准化)?**

- Z-Score 产生负数,加权后"负数表示不相关"语义不直观
- MinMax 严格 [0, 1],权重就是简单占比(w_dense+w_sparse=1)
- 工程上易调试易解释

**Q2: 代码里那个 `if hi-lo < 1e-9: return [1.0]` 是干嘛的?**

```python
def _minmax(values):
    if hi - lo < 1e-9:       # 极端情况:max == min
        return [1.0 for _ in values]   # 全部赋 1.0,不能赋 0
```

兜底:稀疏召回只命中 1 个文档时,max=min,除零错误。**赋 1.0 而不是 0** 是因为"唯一命中的文档对该查询是最相关的",不能因为分母为零把它打没。

**Q3: 为什么是按查询归一化,不是按文档归一化?**

每次查询的 max/min 都不同,所以同一文档在不同查询里的归一化分数**不可比较**。这没问题——融合算法只关心"**这次查询**里,哪个文档最相关",不需要跨查询比较。

**用上面同一个例子算一遍**

Dense 路:min=0.83, max=0.95, range=0.12

```
dense_norm(A) = (0.95-0.83)/0.12 = 1.00
dense_norm(B) = (0.89-0.83)/0.12 = 0.50
dense_norm(C) = (0.87-0.83)/0.12 = 0.33
dense_norm(D) = (0.85-0.83)/0.12 = 0.17
dense_norm(E) = (0.83-0.83)/0.12 = 0.00
```

Sparse 路:min=3.1, max=18.7, range=15.6

```
sparse_norm(A) = (12.3-3.1)/15.6 = 0.59
sparse_norm(B) = (18.7-3.1)/15.6 = 1.00
sparse_norm(C) = (15.1-3.1)/15.6 = 0.77
sparse_norm(D) = (4.2-3.1)/15.6  = 0.07
sparse_norm(E) = (3.1-3.1)/15.6  = 0.00
```

融合(w_dense=0.7, w_sparse=0.3):

```
fused(A) = 0.7×1.00 + 0.3×0.59 = 0.88
fused(B) = 0.7×0.50 + 0.3×1.00 = 0.65
fused(C) = 0.7×0.33 + 0.3×0.77 = 0.46
fused(D) = 0.7×0.17 + 0.3×0.07 = 0.14
fused(E) = 0.7×0.00 + 0.3×0.00 = 0.00
```

排序:A > B > C > D > E(和 RRF 一致,但分数差距更大、更可解释)。

**MinMax 的优缺点**

| 优点 | 缺点 |
|---|---|
| ✅ 保留绝对分数信息 | ❌ **对极值敏感**:一个 0.999 的异常高分把其他文档压到 [0, 0.5] |
| ✅ 权重语义明确(70/30) | ❌ 不能跨查询比较 |
| ✅ 可做 score_threshold 过滤(归一化后 < 0.3 丢) | ❌ sparse 召回弱时(max=min)需兜底 |
| ✅ 调参直观 | ❌ 分数分布严重偏斜时失真 |

#### 5.7.4 两者对比

| 维度 | RRF | MinMax+加权 |
|---|---|---|
| **输入** | 只要排名 | 要原始分数 |
| **量纲问题** | 天然解决 | 归一化解决 |
| **绝对分数** | ❌ 丢失 | ✅ 保留 |
| **极值鲁棒** | ✅ 鲁棒 | ❌ 敏感 |
| **可解释性** | 中(看排名) | 高(看权重 + 分数) |
| **参数语义** | k=60 是黑盒经验值 | 权重 0.7/0.3 一目了然 |
| **工业采用** | ES/OpenSearch/Vespa 内置 | 自定义实现 |
| **适用场景** | 大规模、跨检索器、分数分布未知 | 中小规模、需要 score_threshold 过滤 |

#### 5.7.5 项目里的选择

**默认走 MinMax**(`NORMALIZE_SCORES_BEFORE_FUSION=true`),原因:

1. **保留分数信息** → 后续可做 `score_threshold=0.3` 过滤低相关 chunk
2. **权重语义明确** → 0.7/0.3 直接告诉调参者"更信语义"
3. **文档规模小** → 极值问题在千级 chunk 下不严重

**什么时候应该切回 RRF**:

| 症状 | 原因 | 切换理由 |
|---|---|---|
| Dense top1 是 score=0.99 异常高,其他都 < 0.5 | MinMax 把其他压到 [0, 0.5],区分度丢失 | RRF 只看排名,不受极值影响 |
| Sparse 召回质量差但分数量级大(BM25 普遍 10+) | MinMax 后 sparse 的内部差异被放大,过度加权弱信号 | RRF 让 sparse 只贡献"排名信号",不主导量纲 |

切换方式:`NORMALIZE_SCORES_BEFORE_FUSION=false`,自动走 `app/retrieval/hybrid_searcher.py:53` 的 RRF 分支。

**一个常被忽略的实现细节**

QuillRAG 在 RRF 模式下用的不是教科书原版 `1/(k+rank)`,而是 **`w/(k+rank)`**——把权重塞进了分子。这等价于原版 RRF 后再按权重线性缩放,效果一样,实现更简洁:

```python
bucket["score"] += vector_weight / (rrf_k + rank + 1)
```

**权重调节经验**

- 长查询(自然语言问句):调高 `vector_weight` 到 0.8
- 含错误码、专有名词的短查询:调高 `sparse_weight` 到 0.5

### 5.8 Diversity Penalty(同文档衰减)

**问题**: top_k 可能全是同一篇 PDF 的 chunk,信息密度低。

**算法**:

```python
doc_count = defaultdict(int)
for bucket in fused_sorted_by_score:
    doc_count[bucket.doc_id] += 1
    if doc_count[bucket.doc_id] > 1:
        # 第 2 条开始衰减:第 n 条 *= max(floor, 1 - penalty*(n-1))
        factor = max(0.5, 1.0 - 0.1 * (doc_count[bucket.doc_id] - 1))
        bucket.score *= factor
```

**参数**:

- `penalty=0.1`(衰减系数,0 关闭)
- `floor=0.5`(下限,保证不衰减到 0)

**效果**: 同文档第 2 条 ×0.9,第 3 条 ×0.8,...,第 6 条及以后 ×0.5(触底)。

### 5.9 Cross-Encoder 重排(精排)

**与 Bi-Encoder 的本质区别**:

```
Bi-Encoder(召回阶段):
   query → encoder → q_vec
   doc   → encoder → d_vec
   score = cos(q_vec, d_vec)
   特点: doc 向量可预计算入库,query 来时只算 query 向量,O(1) 检索
   局限: query 和 doc 不交互,精度有限

Cross-Encoder(精排阶段):
   [CLS] query [SEP] doc [SEP] → transformer → score
   特点: query 和 doc 拼一起过模型,捕到交互特征,精度高
   局限: O(n) 慢,只能用在 top_k 较小时(如 top20 → top5)
```

这就是两阶段检索的本质:**用 Bi-Encoder 大网撒,用 Cross-Encoder 精筛**。

**5 个 Provider**(`app/retrieval/reranker.py`):

| Provider | 模型 | 部署 | 适用场景 |
|---|---|---|---|
| `flashrank` | ONNX(ms-marco-TinyBERT 等) | 本地,18-120MB | 2核4G 部署,默认推荐 |
| `local` | BAAI bge-reranker-v2-m3 | 本地,568MB | 有 GPU 或大内存机器 |
| `jina` | jina-reranker-v2-base-multilingual | 在线 API | 免费 1M token/月 |
| `llm` | 任意 OpenAI 兼容模型 | 在线 API | 复用主系统 LLM 给候选打分 |
| `disabled` | 无 | 无 | 关闭,按原 score 排序 |

接口统一为 `compute_scores(query, documents) -> list[float]`,通过工厂函数 `get_reranker()` 按配置返回对应实现。

### 5.10 Jaccard 去重

**问题**: 同一段内容可能因分块边界不同被存成两条高度相似的 chunk。

**算法**: 对返回结果的 token 集合两两计算 Jaccard 相似度,超过阈值(默认 0.7)则丢弃分数低的。

`DEDUP_JACCARD_THRESHOLD=1.0` 即关闭。

---

## 6. 存储设计

### 6.1 Qdrant(向量库)

存所有 chunk 的稠密向量、稀疏向量、payload。

```
Collection
└─ Point(uuid4)
   ├─ vector
   │   ├─ dense:  [0.012, -0.34, ...]      # 3072 维
   │   └─ sparse: {indices: [12, 873], values: [1.0, 2.0]}
   └─ payload
       ├─ content:      "公式正文"
       ├─ doc_id:       "a3f5..."
       ├─ chunk_index:  7
       ├─ category:     "formula"
       ├─ heading_path: ["第三章", "3.2 系数"]
       ├─ page:         12
       ├─ logic_idx:    34
       ├─ prev_view_id: "a3f5...:6"
       ├─ next_view_id: "a3f5...:8"
       └─ extra:        {latex: "...", text: "...", bbox: [...]}
```

**注意**: 不存在"分表存储"。text/table/formula/figure 都是同一个 collection 里的 point,通过 `payload.category` 字段过滤区分。

### 6.2 SQLite(元数据)

只存**文档级**元数据,**不存 chunk**。两张表:

```sql
-- 文档主表
CREATE TABLE documents (
    doc_id        TEXT,           -- 内容指纹
    collection    TEXT,           -- 所属 collection
    source        TEXT,           -- 原始文件名
    category      TEXT,           -- 文档类型(可选)
    chunk_count   INTEGER,        -- chunk 总数
    content_hash  TEXT,           -- md5,幂等判断
    extra         TEXT,           -- JSON 扩展字段
    ingested_at   TEXT,
    PRIMARY KEY (doc_id, collection)
);

-- 版本历史
CREATE TABLE document_versions (
    version_id   TEXT PRIMARY KEY,
    doc_id       TEXT,
    collection   TEXT,
    content_hash TEXT,
    chunk_count  INTEGER,
    created_at   TEXT,
    note         TEXT             -- 如 "updated from <prev_hash>"
);
```

**设计决策**: SQLite 独立于主系统 MySQL,让 QuillRAG 可独立部署给任何项目复用,不依赖外部数据库。

### 6.3 chunk_id 的编码方式

`chunk_id` 不入库单独索引,而是按规则编码后存到 Qdrant payload:

```python
chunk_id = f"{doc_id}:{chunk_index}"
```

需要按 doc_id 找所有 chunk 时,用 Qdrant 的 `Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])` 过滤即可。

---

## 7. 工程化亮点

### 7.1 模型懒加载

服务启动不预加载模型(Cross-Encoder 568MB~2GB),首次调用时后台线程加载,加载期间 `/health=loading`。加载完成 `/health=ready`,失败 `/health=failed`。

### 7.2 全链路降级

每一层都有降级路径,任何单点故障都有兜底:

| 故障 | 兜底 |
|---|---|
| MinerU API 挂 | PyMuPDF 本地启发式解析 |
| Qdrant 挂 | HTTP 503,让主系统走无 RAG 分支 |
| Embedder 挂 | 自动切纯 BM25 召回 |
| Reranker 挂 | 按原 score 排序返回 |
| Sparse 向量索引不存在 | payload scroll + 客户端词频匹配 |

### 7.3 幂等入库

md5 内容指纹 + doc_id 查重,同一文档二次入库直接 noop,避免重复消耗 Embedding API 配额。

### 7.4 版本回溯

每次更新都记 `previous_hash`,SQLite `document_versions` 表保留全量历史,支持 diff 与回滚。

### 7.5 可观测性

- `request_id` 贯穿日志,可串联一次请求的全部日志
- JSON / Text 双格式日志(开发用 text,生产 ELK 用 json)
- 慢请求阈值告警(`SLOW_REQUEST_MS=2000`)
- Prometheus 指标埋点(`ingest_latency_seconds`、`ingest_chunks_total` 等)

### 7.6 双层鉴权

- `X-API-Key` 头:服务间调用
- Session Cookie:浏览器 UI 登录

`/health` 和 `/docs` 公开,其他路径需要其中一种鉴权方式。

---

## 8. 性能参考

CPU 4 核环境下的单次延迟:

| 操作 | 延迟 |
|---|---|
| `/parse` Markdown 1 万字 | < 200ms |
| `/parse` PDF 10 页(含 OCR) | ~2s |
| `/ingest` 同上 + Embedding | 加 100-300ms |
| `/retrieve` hybrid top 10 | 200-500ms(Embedder 已加载) |
| `/rerank` top 5 from 20 | 600-1000ms |

千级 chunk 规模下完全可用,更大规模需考虑分片与缓存。

---

## 9. 扩展点

| 扩展方向 | 实现位置 | 说明 |
|---|---|---|
| 替换 PDF 版面分析为 LayoutLMv3 / PP-Structure | `app/parser/layout/analyzer.py` | 接口已抽象 |
| 自训练 Embedding | `app/retrieval/embedder.py` | 替换 sentence-transformers 加载逻辑 |
| 多租户隔离 | `app/services/collection_service.py` | 用 collection 名做命名空间 |
| 评估平台 | `app/evaluation/` + `scripts/eval_retrieval.py` | recall@k, precision@k, MRR, NDCG@k |
| 语义锚点升级为混合方案 | `app/parser/mineru/parser.py:_anchor_path_for` | 空间距离预筛 + embedding 精排,解决双栏跨栏错配(参考 airQA) |
| 知识图谱增强 | (未实现) | 与上下游集成时再考虑 |
