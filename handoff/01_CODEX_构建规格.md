# CODEX 构建规格(Build Spec)

> **读者:** codex(内网外编码 agent)。
> **你的使命:** 把这套 Confluence 卡片问答 PoC **在进内网前能写的代码全部写完并跑通**——后端 pipeline、评测(eval)harness、前端看板。所有内网依赖用 **fake / 本地等价物** 顶上,真适配器留 stub 给内网的 opencode。
> **先读:** `00_交接说明_README.md`,以及 `RAG_PoC_Implementation_Spec.md` 与 `card_ingestion_sop/`(领域规则在那,本文件不重复)。
> **语言:** 注释/文档可中文;**代码、字段名、schema、接口、配置键一律英文**。

---

## 0. 任务边界(最重要,先看)

**你要做的:** 面向 4 个端口(§2)编程,实现端口之外的**全部**代码,并用 fake/本地实现把整条链端到端跑通,产出一份样例 eval 报告 + 可演示的看板。

**你不要做的:**
- 不要实现真 MCP 抓取、不要接真 gpt-5.5、不要写死任何内网地址/密钥——这些是 opencode 的活,你只留**接口 + stub + 配置位**。
- 不要"为了能跑"把领域规则简化掉:map/reduce/检索/评测的规则以 `RAG_PoC_Implementation_Spec.md` 和 `card_ingestion_sop/skills/*` 为准,逐条实现。

**判断某段代码该不该现在写完的准则:** 它是否只依赖那 4 个端口的**接口**?是 → 现在写完,用 fake 测。否(直接依赖内网具体实现)→ 留 adapter stub。

---

## 1. 项目背景速览(1 分钟)

目标:让 LLM 基于本部门 Confluence 回答问题并**引出原文**。架构是 **卡片优先 + 按需回原文下钻 + 纯 RAG 兜底**(讨论稿 §6,推荐方案三):

- **ingest**:抓页 → 解析 `tree_path` → 按 `##/###` 结构感知切块(spec §5)。
- **map**(逐页):每段抽 concepts/keywords/info_type/**三档 tier**(narrative/inline-value/pointer-only)/摘要/假设问题 + 锚点(card-map skill)。
- **reduce**(跨页):关键词**归一化** → 合并成**卡片** → 精确字段 grounding 回原文 → 冲突按 version 取新+标注 → 产出 **keyword→page 倒排表** + review_queue(card-reduce skill)。
- **load**:离线落 JSON store(`refs`/`descriptions`/`summaries`);内网如有 pgvector 再切换 store adapter(spec §7)。
- **retrieve**:metadata 过滤 → 向量 + 全文(tsvector)→ **RRF** 融合 → rerank → top_k(spec §9)。
- **answer**:gpt-5.5 带引用作答,无依据则拒答(spec §9)。
- **agentic 选择层**:卡片直答 / 顺锚点下钻取原文 / 纯 RAG 兜底,按"意图 + 字段诚实度"决定下钻(讨论稿 §6.3)。
- **eval**(PoC 唯一真正交付物):冻结 golden set,跑变体矩阵,算指标(含 `association recall`、`漏钻率`),出对比报告 → 看板。

---

## 2. 架构:端口与适配器(Ports & Adapters)

定义 4 个端口接口;每个端口给**两套实现**:`fake/local`(你写,内网外可跑)与 `intranet`(stub,opencode 填)。其余代码只依赖端口接口。

```python
# backend/ports.py  —— 仅接口,禁止在此 import 任何具体实现
from typing import Protocol, Literal, Optional

class PageRef(TypedDict):
    page_id: str; title: str; tree_path: list[str]; update_at: str; confluence_version: int

class RawPage(TypedDict):
    # 与 spec §4 的 MCP 字段一致
    page_id: str; title: str; space: str; source_url: str; owner: str
    labels: list[str]; captured_at: str; update_at: str; confluence_version: int
    tree_path: list[str]          # 已从标题/正文间解析出来
    body_md: str                  # Markdown 正文(表格 Markdown;图片本地路径)

class ConfluenceSource(Protocol):
    def list_pages(self, slice_root: str) -> list[PageRef]: ...
    def get_page(self, page_id: str) -> RawPage: ...

class LLM(Protocol):
    # 统一走"给 prompt + 期望 JSON schema,返回校验过的 dict"
    def complete_json(self, system: str, user: str, *,
                      schema: dict, temperature: float = 0.0,
                      max_tokens: int = 2048) -> dict: ...

class Embedder(Protocol):
    def embed(self, texts: list[str], *, kind: Literal["query", "passage"]) -> list[list[float]]: ...
    @property
    def dim(self) -> int: ...

class Hit(TypedDict):
    ref_id: int; score: float; source: Literal["vector", "fts"]

class VectorStore(Protocol):
    def init_schema(self) -> None: ...                # 建表(spec §7 DDL)
    def upsert_refs(self, rows: list[dict]) -> None: ...
    def upsert_descriptions(self, rows: list[dict]) -> None: ...
    def upsert_summaries(self, rows: list[dict]) -> None: ...
    def search_vector(self, table: str, query_vec: list[float], k: int,
                      filters: Optional[dict] = None) -> list[Hit]: ...
    def search_fts(self, table: str, query_text: str, k: int,
                   filters: Optional[dict] = None) -> list[Hit]: ...
    def get_refs(self, ref_ids: list[int]) -> list[dict]: ...
```

**内网外实现(你写):**

- `FileConfluenceSource(fixtures_dir)` —— 读 `fixtures/confluence/*.md`(§8 你自己造),解析 front-matter 当 metadata、正文当 `body_md`。
- `MockLLM` —— **确定性**:对抽取/归一化/作答/judge 各任务用规则返回,保证可重复(测试用)。如未来需要按 prompt hash 固定返回,再把 canned JSON 放入 `fixtures/llm_canned/`。**另给** `OpenAICompatLLM(base_url, model, api_key)` —— 走 OpenAI 兼容协议,方便内网 gpt-5.5 只改 `base_url/model`。
- `HashEmbedder` —— 确定性 lexical/hash embedding,无需下载模型,用于内网外和无模型环境 dry run。真实 embedding 由 `IntranetEmbedder` 或配置替换。
- `JsonVectorStore(path)` —— 本地 JSON store,无需 Docker,用于端到端 demo。若内网已有 pgvector/数据库服务,再实现/启用 `PgVectorStore(dsn)`。

**内网内实现(留 stub,opencode 填,见 `02_OPENCODE_内网补充.md`):**

- `McpConfluenceSource` / `Gpt55LLM` / `IntranetEmbedder`(若与 BGE-m3 不同)/ pgvector 的内网 `dsn`。

> **依赖注入:** 用一个 `factory.py` 按 `config.yaml` 的 `providers.*` 选择实现。切换内网外只改配置,不改业务代码。

---

## 3. 仓库结构

```
RAG_solution/
├─ backend/
│  ├─ ports.py                 # 4 个端口接口(§2)
│  ├─ factory.py               # 按 config 选择实现(DI)
│  ├─ config.py / config.yaml  # 配置加载 + 默认配置
│  ├─ adapters/
│  │  ├─ confluence_file.py    # FileConfluenceSource(可跑)
│  │  ├─ confluence_mcp.py     # McpConfluenceSource(stub)
│  │  ├─ llm_mock.py           # MockLLM(可跑)
│  │  ├─ llm_openai_compat.py  # OpenAICompatLLM(可跑)
│  │  ├─ llm_gpt55.py          # Gpt55LLM(stub)
│  │  ├─ embedder_hash.py      # HashEmbedder(可跑,无需下载模型)
│  │  ├─ embedder_intranet.py  # IntranetEmbedder(stub)
│  │  ├─ store_json.py         # JsonVectorStore(可跑,无需 Docker)
│  │  └─ store_pgvector.py     # PgVectorStore(stub/内网已有服务)
│  ├─ ingest/                  # capture + parse tree_path + chunk(spec §4–5)
│  ├─ mapper/                  # 实现 card-map skill → map_*.json
│  ├─ reducer/                 # 实现 card-reduce skill → cards/倒排表/review_queue
│  ├─ load/                    # 写入 VectorStore(JSON dry run / pgvector)
│  ├─ retrieve/                # filter→vector+fts→RRF→rerank→top_k(spec §9)
│  ├─ answer/                  # gpt-5.5 作答 + 引用 + 拒答(spec §9)
│  ├─ agentic/                 # 选择层下钻决策(讨论稿 §6.3)
│  ├─ eval/                    # golden 生成 + 变体跑分 + 指标 + 报告(§6)
│  ├─ schemas/                 # 所有 JSON schema(§4)+ 显式校验
│  ├─ pipeline.py              # CLI:ingest/map/reduce/load/retrieve/eval 各子命令
│  └─ tests/                   # 端到端 + 单元(用 fixtures)
├─ frontend/                   # 评测看板(§7)
├─ fixtures/                   # 已提供:confluence/ 11 页 + golden_seed/;llm_canned/ 预留(§8)
├─ outputs/                    # 运行产物:map/ cards/ inverted_index/ review_queue/ eval_report.json
├─ pyproject.toml              # uv sync / uv run 入口
├─ Makefile / run_demo.ps1     # one-command demo/test/serve
└─ README.md                   # 如何本地跑通(你写)
```

> **后端语言:** Python(与 spec 的 pgvector/RAGAS/embedding 生态一致)。前端语言/框架你定(§7)。

---

## 4. 数据契约(Data Contracts —— 交接的命根子)

**这些 schema 是前后端、map/reduce、eval 之间的硬约定。** 大部分已在 skill 里定义,这里集中列出权威来源 + 补 eval 专属的。请在 `backend/schemas/` 落成模型/显式校验并在 IO 处校验;不强制依赖 pydantic。

| 数据 | 权威定义 | 说明 |
|---|---|---|
| `RawPage` | 本文件 §2 / spec §4 | MCP 抓取产物 |
| map 输出 `map_<page_id>.json` | `card-map/SKILL.md` §3.1 | 逐页抽取;含 sections[].{anchor, concepts, keywords_raw, info_type, tier, fact_value, pointer_to, summary_*, questions_*, confidence} + page_summary |
| 卡片 `cards/*.json` | `card-reduce/SKILL.md` §3.2 | 含 fields[].{field, tier, value, authoritative, conflict, conflict_detail, sources[], soft_links} |
| 倒排表 `inverted_index.jsonl` | `card-reduce/SKILL.md` §3.3 | 一行一个 canonical→page/anchor 关联 |
| review_queue `review_queue.jsonl` | `card-reduce/SKILL.md` §3.4 | 给 Business 的存疑项 |
| 受控词表 | `templates/canonical_keywords_受控词表.md` | reduce 回写;字段见该文件 |
| pgvector 表 | spec §7 DDL | `refs / descriptions / summaries` |

**eval 专属 schema(本文件新增,前端按它渲染):**

```json
// outputs/golden_set.json  —— 冻结的评测题(§6.1)
{
  "frozen_hash": "sha256(...)",
  "items": [
    {"q_id": "G-001", "q_en": "...", "q_zh": "...",
     "type": "single|multihop|identifier-lookup|pointer-drill|out-of-scope",
     "gold_section_ids": ["page_id#heading_path", "..."] ,   // 或 "NO_ANSWER"
     "gold_answer": "...", "human_checked": true}
  ]
}
```

```json
// outputs/eval_report.json  —— 跑分结果(看板的唯一数据源)
{
  "run_id": "2026-06-04T12:00:00Z", "embedding_model": "bge-m3", "judge": "mock|gpt-5.5",
  "golden": {"size": 50, "by_type": {"single": 18, "multihop": 8, "identifier-lookup": 12, "pointer-drill": 7, "out-of-scope": 5}, "frozen_hash": "..."},
  "baseline_id": "V1",
  "variants": [
    {"id": "V1", "label": "body·vector·norerank·pure-rag",
     "index": "body", "search": "vector", "rerank": false, "answer_source": "pure-rag",
     "metrics": {
       "recall@5": 0.62, "recall@8": 0.71, "mrr": 0.55, "ndcg@8": 0.60,
       "faithfulness": 0.78, "answer_relevancy": 0.74, "context_precision": 0.66, "context_recall": 0.70,
       "association_recall": null, "drill_miss_rate": null   // 仅卡片/agentic 变体有值
     }}
    // V2..V6 + agentic 变体...
  ],
  "items": [
    {"q_id": "G-001", "type": "identifier-lookup", "q": "...", "gold": ["..."],
     "per_variant": {
       "V1": {"hit@8": false, "retrieved": ["..."], "answer": "...", "faithfulness": 0.4, "drilled": null},
       "V6": {"hit@8": true,  "retrieved": ["..."], "answer": "...", "faithfulness": 0.95, "drilled": true}
     }}
  ]
}
```

---

## 5. 后端模块逐项(每个标注:权威规则 / 端口依赖 / 现在能否写完)

> 凡"现在能写完=是"的,用 fixtures + fake 端到端测;凡涉及端口,只调接口。

1. **config + factory** —— 加载 `config.yaml`,按 `providers.{confluence,llm,embedder,store}` 注入实现。能写完=是。
2. **ingest**(端口:`ConfluenceSource`)—— `list_pages(slice_root)` → 逐页 `get_page` → 解析 `tree_path` → 落 `outputs/capture/<page_id>.json`。规则:spec §4。能写完=是(用 `FileConfluenceSource`)。
3. **chunk** —— 按 `##/###` 建 heading 树切块;**表格/代码/列表不切断、小段合并、大段二次切+overlap、无 heading 退化**;打 `has_table/has_image`、`heading_path`。规则:spec §5。纯代码,能写完=是。
4. **mapper**(端口:`LLM`)—— 对每 section 用 `card-map/SKILL.md §3.2` 的 prompt 调 `LLM.complete_json` 抽字段;页级 summary 节点;严格按 §3.1 schema 输出 `outputs/map/map_<page_id>.json`。**三档诚实、关键词照抄、锚点必填**(skill §4)。能写完=是(MockLLM/本地模型)。
5. **reducer**(端口:`LLM`)—— 归一化(§3.1 聚类 prompt)→ 更新词表 → 合并卡片(模板 §4)→ 精确字段 grounding → 冲突取新+标注 → 倒排表 → review_queue。规则:`card-reduce/SKILL.md`。能写完=是。
6. **load**(端口:`Embedder` + `VectorStore`)—— embed → 写 `refs/descriptions/summaries`。离线 demo 用 hash embedding + JSON store;内网若接 pgvector 再建表(spec §7 DDL)并写 tsvector。
7. **retrieve**(端口:`Embedder` + `VectorStore`)—— metadata 过滤 → 向量 + FTS 两路 → **RRF 融合**(`rrf_k=60`)→ 去重 → rerank(`bge-reranker-v2-m3`,开源可本地)→ top_k=8。规则:spec §9。`index/search/rerank` 做成**开关**(喂变体矩阵)。能写完=是。
8. **answer**(端口:`LLM`)—— 取 top_k 原文 → gpt-5.5 作答,**强制引用 source_url、无依据则 "no answer found"**。规则:spec §9。能写完=是。
9. **agentic 选择层**(端口:`LLM` + 检索)—— 实现讨论稿 §6.3 流程:命中卡片?→ 意图(概念/精确)→ 看字段 tier(narrative/inline-value 可直答;pointer-only/缺失→下钻取原文)→ 兜底纯 RAG。记录每次是否 `drilled`(供 `漏钻率`)。能写完=是。
10. **eval** —— 见 §6。能写完=是。
11. **pipeline.py(CLI)** —— 子命令:`ingest|map|reduce|load|retrieve|answer|eval|demo`;`demo` 一键全跑 fixtures 出报告。能写完=是。

---

## 6. 评测 harness(eval —— PoC 的核心交付,务必扎实)

权威规则:`RAG_PoC_Implementation_Spec.md` §11 + 讨论稿 §8。要点:

### 6.1 golden 生成(`eval/golden_gen.py`,端口:`LLM`)
- 来源 = **留出的原文页**(holdout),**不是卡片**——否则循环验证、`association_recall` 虚高。
- 用**与索引/卡片不同的 prompt**,模仿真实用户口吻(口语/关键词/含糊),中英双语(spec §11.1)。
- 题型 + 默认配比:`single` / `multihop`(gold=多 section)/ `identifier-lookup` / `pointer-drill`(卡片只有指针,测下钻)/ `out-of-scope`(gold=NO_ANSWER)。
- 每题标 `gold_section_ids` + `gold_answer` + `type`;输出 §4 的 `golden_set.json` 并**冻结**(存 `frozen_hash`)。
- 产出一个 `human_check` 清单(随机 ~20%)供人工抽检,标记 `human_checked`。

### 6.2 变体矩阵(`eval/variants.py`)
按 spec §10 的阶梯 V1–V6,**外加卡片/agentic 变体**(讨论稿 §8.3):`answer_source ∈ {pure-rag, card-direct, card+grounding, agentic}`。一次只动一维以归因。所有变体跑**同一冻结 golden**。

### 6.3 指标(`eval/metrics.py`)
- 检索:`recall@k(5,8)`、`MRR`、`nDCG@8`(自实现,基于 gold_section_ids)。
- 端到端:离线 demo 先用 mock/规则指标输出同名字段;内网接 gpt-5.5 judge 后再用 **RAGAS** 或等价 judge 计算 `faithfulness/answer_relevancy/context_precision/context_recall`。
- **卡片专属(自实现,重点)**:
  - `association_recall` = 对每个概念,gold 应关联的页里,倒排表实际关联上的比例。gold 关联来自 golden/Business(内网外先用 fixtures 标注)。
  - `drill_miss_rate`(漏钻率)= `pointer-drill` + `identifier-lookup` 题中,本该下钻却用卡片直答的比例(用 §9 记录的 `drilled` 判定)。
- **judge**:LLM-as-judge 走 `LLM` 端口;内网外用 MockLLM/本地模型,**留校准钩子**(~10 条人工标注先校准,spec §11.2)。

### 6.4 报告(`eval/report.py`)
汇总成 §4 的 `eval_report.json`(变体指标 + 逐题 per_variant),写 `outputs/`。这是看板唯一数据源。

---

## 7. 前端看板(给领导看 —— 要观赏性与流畅性)

**用途:** 向领导展示"我们客观比了多套方案,这套最好"。**技术栈你定**(React/Vue/Svelte + 图表库,或精致单页都行),但硬要求:

- **演示级视觉**:统一设计系统、留白讲究、投影/大屏清晰、过渡平滑、响应式;支持浅/深色更好。
- **数据源 = `outputs/eval_report.json`**(静态读取即可;也可起一个极薄的只读 API)。**不依赖内网**,任何地方都能演示。
- **必备视图:**
  1. **概览(Hero)**:冠军变体 vs baseline 的头条指标(`recall@8`、`faithfulness`、`association_recall`、`漏钻率`)做成大数字卡 + 同比 baseline 的涨跌箭头。一眼看懂"提升了多少"。
  2. **变体对比**:V1–V6 + agentic 的指标对比(柱状/雷达),标出阶梯每一步加了什么、带来多少增益。
  3. **卡片价值专区**:重点突出 `association_recall`(补漏页有没有用)和 `漏钻率`(精确题准不准)——这是卡片方案的故事线。
  4. **逐题下钻**:点变体 → golden 题列表,按 `type` 过滤;展开一题看 检索到的 vs gold、答案、faithfulness、是否 drilled。失败题一眼可见(这也是 bad case 的来源)。
  5. **题型分布**:golden 的 5 类占比 + 各类表现。
- **细节**:数字带单位/百分比与小数位统一;空值(baseline 无 `association_recall`)优雅留空;加载/切换有 skeleton 或动效;可一键导出当前视图为图片/PDF 方便放进汇报。
- **交付**:`frontend/` 自带 README(如何本地 serve)+ 一份用样例 `eval_report.json` 的可访问看板,证明可演示。

---

## 8. Mock / fixtures(已提供 —— 直接用,不用从零造)

**假 Confluence 页和起步 golden 已经在仓库里了**,详见 `fixtures/README.md`。它们刻意埋了真实数据会出的坑,跑一遍就能验证代码处理得对不对。你不用再造,只需读取/扩展:

- `fixtures/confluence/` —— **11 个假页**(front-matter=metadata,正文=body_md;`tree_path` 已解析成数组),域覆盖 `DM / Journey / Adaptor / MDC OTP / SFMC / Message Inventory / …`,树路径在 `06-Delivery/10. Planned Project/2026 Planned Project/...`。已埋的坑(逐页见 `fixtures/README.md`):
  - 别名 `DM plugin / Data Management / DMP`(归一化 `map-001`)、拼写 `adaptor/adapter`。
  - `batch_size` 跨页冲突:500(页 123456,v7)vs 1000(页 777001,v3 但 update_at 更晚)→ 取新+标注(`reduce-001`)。
  - "supports retry configuration" 不给数值 → `pointer-only`,真值在 Overview(测漏钻 `map-002`)。
  - 多跳:DM→adaptor→Journey 散在多页;Message Inventory 也提 DM 批处理(测 `association_recall` 漏页)。
  - 越界材料(容量页)→ 部分问题应 `NO_ANSWER`(测拒答)。
- `fixtures/golden_seed/golden_seed.jsonl` —— **15 题起步集**,覆盖五类、gold 指向真实 heading(section id = `page_id#H2标题`)。**你的活:扩到 ~50 条**(配比见 §6.1),保持与索引/卡片 prompt 解耦。
- `fixtures/llm_canned/` —— 预留目录:如未来需要 prompt-hash canned responses 再生成;当前 MockLLM 在代码里确定性返回。

> 你在本节的净工作 = 写 `FileConfluenceSource` 读这些页 + 跑通 15 题起步 golden;扩到 ~50 题建议在真实切片稳定后结合人工抽检再做。

---

## 9. 验收标准(Definition of Done —— 自检清单)

- [ ] `uv sync`;`uv run python -m backend.pipeline demo`(或等价)**一条命令**跑通 ingest→map→reduce→load→retrieve→answer→eval,产出 `outputs/eval_report.json`。
- [ ] 4 个端口**各有 fake/local 实现(可跑)+ intranet stub(留空但签名完整、有清晰 TODO 注释)**。
- [ ] map/reduce 输出**严格符合** card-map/card-reduce skill 的 schema(有 schema 校验测试)。
- [ ] 检索把 `index/search/rerank/answer_source` 做成**配置开关**,变体矩阵能跑全 V1–V6 + agentic。
- [ ] eval 实现 `recall@k/MRR/nDCG` + mock/RAGAS-compatible 四项 + **自实现 `association_recall` 与 `drill_miss_rate`**;golden **与索引 prompt 解耦**且**冻结**。
- [ ] 用**已提供的** `fixtures/`(11 页 + 15 题 golden_seed)端到端跑通;报告里能看到已知坑被正确处理(DMP 归一化、batch_size 冲突取新+标注、漏钻、拒答、Message Inventory 关联回 DM)。
- [ ] 前端 `frontend/` 无需构建即可 serve,读样例 `eval_report.json` 渲染 §7 全部视图,**视觉达演示级**。
- [ ] 单元 + 端到端测试通过;根 `README.md` 写清本地如何跑。
- [ ] 全程**零内网依赖**:没有真 MCP/gpt-5.5/内网地址;切到内网只需改 `config.yaml` + 由 opencode 实现 stub。

---

## 10. 明确不要做的(留给 opencode)

- 不实现 `McpConfluenceSource` 的真 MCP 调用(只留接口 + stub + 注释说明需要哪些 MCP 能力)。
- 不接真 `Gpt55LLM`(留 stub;但 `OpenAICompatLLM` 要能用,内网大概率只换 `base_url/model`)。
- 不写死内网 embedding;若内网模型≠BGE-m3,留 `IntranetEmbedder` stub(注意 `dim` 要与建表维度一致,超 2000 维用 `halfvec`,spec §7 注)。
- 不配置内网 pgvector 连接(只留 `dsn` 配置位)。
- 这些都在 `02_OPENCODE_内网补充.md` 里交代清楚,你只需保证**接口干净、stub 有清晰 TODO**。

---

*完成后,把可运行仓库 + 样例报告 + 看板交回。内网内的最后一公里见 `02_OPENCODE_内网补充.md`。*
