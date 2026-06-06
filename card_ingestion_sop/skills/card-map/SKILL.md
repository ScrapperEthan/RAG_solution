---
name: card-map
description: >
  对单个 Confluence 页面做"逐页抽取"(map 阶段)。输入一页 MCP 抓取的内容,输出一份结构化的
  map JSON:本页涉及哪些关键词/概念、每段是什么类型(what-is/config/...)、属于哪一档
  (narrative/inline-value/pointer-only)、一句话摘要 + 假设问题、以及回原文的锚点(anchor)。
  这是构建卡片(card)和 keyword→page 倒排表的地基。当需要"把一页 Confluence 变成可合并的原料"时使用本 skill。
---

# card-map —— 逐页抽取 skill(给 opencode 读)

> 一句话:**把一页 Confluence,变成一份"机器和人都能看懂的结构化摘要 + 回原文的指针"。**
> 本文件中文为主;**字段名、JSON、prompt 一律保留英文**,因为它们要直接进代码和喂给 LLM,英文最无歧义。

---

## 0. 给初学者:这个 skill 在整条流水线里做什么?

整条流水线是一个 **map → reduce** 的过程(像把一堆文件先逐份做笔记,再把笔记按主题汇总):

```
                你在这里 ↓
  Confluence 页  ──►  [card-map]  ──►  per-page map JSON  ──►  [card-reduce]  ──►  卡片 + 倒排表
   (MCP 抓下来)       逐页抽取            (一页一个文件)          跨页合并            (最终产物)
```

- **map(本 skill)= 逐页**:对切片里的**每一页**都跑一遍,各自产出一份 JSON。页与页之间**互不影响**,所以可以并行、可以单页重跑。
- **reduce(下一个 skill)= 跨页**:把所有 map JSON 按"同一个主题"汇总成一张卡片。

**为什么 map 要全量跑(不是只跑业务点名的页)?** 因为 keyword→page 的关联是靠"每页自报关键词"建起来的。漏跑一页,那页就永远进不了索引,后面也捞不回来。详见 SOP 主文档"为什么全量 map"。

---

## 1. 输入(opencode 会拿到什么)

一页 Confluence 经 MCP 抓取后的对象,字段如下(与既有 `RAG_PoC_Implementation_Spec.md` §4 一致):

```
title, source_type, confluence_space, confluence_page_id, source_url,
owner, labels, captured_at, update_at, confluence_version
+ body(Markdown 正文:标题/段落;表格是 Markdown;图片是本地路径引用)
```

注意:**`tree_path`(祖先路径,如 `06-Delivery/10. Planned Project/2026 Planned Project`)目前夹在标题和正文之间**,要在解析时抽到独立字段,不要留在 `body` 里。

**可选输入:`canonical_keywords`(受控词表,由**同事的 topic/keyword 组件**产出、Business 审批的外部表)。** 如果 `../../templates/canonical_keywords_受控词表.md` 已经有内容,把已审批的 `canonical_name + aliases` 读进来,**用于在 `concepts` 里尽量复用已有的规范名**。但即使读了词表,**`keywords_raw` 仍要按原文照抄**(见 §4 硬规则 R3)——归一化是 reduce 的活,map 只负责忠实记录。

---

## 2. 步骤(opencode 照着做)

map 分两类活:**确定性解析(写代码)** 和 **语义抽取(调 gpt-5.5)**。分清楚谁干哪个,能省 token、也更稳。

### Step 1 — 解析页面(代码,不用 LLM)

1. 把 `tree_path` 从标题/正文之间解析出来,存成数组。
2. 按 Markdown heading `##`(H2)/`###`(H3)把正文切成 section,建一棵 heading 树;每个最深一层 heading + 它下面的正文 = 一个候选 section。完整 heading 路径(`H1 > H2 > H3`)记为 `heading_path`。
3. 切块规则(**别"见 ## 就切"**,与 spec §5 一致):
   - 表格 / 代码块 / 列表**绝不从中间切断**。
   - 太小的 section(< ~100 token)**向上并入父级**。
   - 太大的 section(> ~1000 token)在段落边界**二次切分**,留 ~50 token overlap。
   - 第一个 heading 之前的引言、以及完全没有 heading 的页 → 退化成按段落/长度切。
4. 给每个 section 打 `has_table` / `has_image`(布尔,代码判断即可)。
5. 图片:PoC 不做图片向量化。用周边文字让 LLM 生成一句 caption 内联进正文(便于检索),图片本地路径留在 metadata,`has_image=true`。

### Step 2 — 逐 section 语义抽取(调 gpt-5.5,用 §3 的 prompt)

对每个 section 抽出下面这些(**这是 map 的核心**):

| 字段 | 含义 | 谁来填 |
|---|---|---|
| `concepts` | 本段讲的主题/概念,尽量用词表里的规范名(没有就用原文叫法) | LLM |
| `keywords_raw` | 本段出现的关键词/别名,**原样照抄**(`DM plugin` / `Data Management plugin` / `DMP` 都收) | LLM |
| `info_type` | 内容类型,受控词表:`what-is \| how-to \| config \| troubleshoot \| reference \| decision \| meeting-notes` | LLM |
| `tier` | 信息档位(见下),`narrative \| inline-value \| pointer-only` | LLM |
| `fact_value` | 仅当 `tier=inline-value`:把那个精确值**原样**摘出(如 `max_retry: 3`) | LLM |
| `pointer_to` | 仅当 `tier=pointer-only`:值在哪(如 `PageB#Configuration`) | LLM |
| `summary_en/zh` | 一句话摘要,中英各一 | LLM |
| `questions_en/zh` | 3–7 条本段能回答的"假设问题",中英,含口语和关键词式各一条 | LLM |
| `confidence` | LLM 对本段抽取的自评把握度 0–1 | LLM |

**三档(tier)是整套方案的命门,务必理解(对应讨论稿 §6.2):**

| tier | 它意味着什么 | 例子 |
|---|---|---|
| `narrative` | 定义 / 功能 / 关系类的叙述,可被总结 | "DM plugin 负责把消息投递到各渠道" |
| `inline-value` | 一个**精确值**,连同出处一起原样搬 | `max_retry: 3`(来源 `PageB#Configuration`) |
| `pointer-only` | 本段**没有**那个值,只知道值在别处 | "重试相关配置见 `PageB#Configuration`" |

> **为什么分档?** 因为下游的答题 agent 要据此决定"能不能直接答"。narrative 和 inline-value 能直接答,pointer-only 必须回原文取证。**关键纪律见 §4 R1:绝不为了凑一个 inline-value 而编造数值——没有确切值,就老老实实标 pointer-only。**

### Step 3 — 生成页面级 summary 节点(调 gpt-5.5)

每页额外产出一个 `page_summary`:把全页各部分如何关联综合成一段话 + 2–4 条跨段的"全貌/综合"问题(中英)。**用途**:回答"how do X and Y work together"这类跨段问题时先命中它,再指向多个 section(对应 spec §6.2)。

### Step 4 — 组装输出

按 §3 的 schema 拼成一份 per-page map JSON,文件名建议 `map_<page_id>.json`,存到 `outputs/map/`。

---

## 3. 输出 schema + LLM prompt

### 3.1 per-page map JSON(完整 schema)

```json
{
  "page_id": "123456",
  "source_url": "https://confluence/.../DM-Plugin-Overview",
  "title": "DM Plugin Overview",
  "space": "DEPT",
  "tree_path": ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Plugins"],
  "owner": "alice",
  "labels": ["plugin", "delivery"],
  "confluence_version": 7,
  "update_at": "2026-05-20T10:00:00Z",
  "captured_at": "2026-06-03T08:00:00Z",
  "page_summary": {
    "summary_en": "Overview of the DM plugin: what it is, its config, and how it links to the Journey plugin.",
    "summary_zh": "DM plugin 总览:定义、配置、以及它如何与 Journey plugin 衔接。",
    "cross_questions_en": ["How does the DM plugin work with the Journey plugin?"],
    "cross_questions_zh": ["DM plugin 和 Journey plugin 怎么配合?"]
  },
  "sections": [
    {
      "anchor": "DM Plugin Overview > What is the DM Plugin",
      "heading_path": ["DM Plugin Overview", "What is the DM Plugin"],
      "concepts": ["DM plugin"],
      "keywords_raw": ["Data Management plugin", "DM plugin", "DMP"],
      "info_type": "what-is",
      "tier": "narrative",
      "fact_value": null,
      "pointer_to": null,
      "has_table": false,
      "has_image": false,
      "summary_en": "Defines the DM plugin and its role in message delivery.",
      "summary_zh": "定义 DM plugin 及其在消息投递中的职责。",
      "questions_en": ["What is the DM plugin?", "DM plugin purpose"],
      "questions_zh": ["DM plugin 是什么?", "DM plugin 干嘛的"],
      "confidence": 0.9
    },
    {
      "anchor": "DM Plugin Overview > Configuration",
      "heading_path": ["DM Plugin Overview", "Configuration"],
      "concepts": ["DM plugin configuration"],
      "keywords_raw": ["batch_size", "max_retry", "DM plugin config"],
      "info_type": "config",
      "tier": "inline-value",
      "fact_value": "batch_size default 500; max_retry: 3",
      "pointer_to": null,
      "has_table": true,
      "has_image": false,
      "summary_en": "DM plugin config params: batch_size default 500, max_retry 3.",
      "summary_zh": "DM plugin 配置项:batch_size 默认 500、max_retry 3。",
      "questions_en": ["What is the default batch_size for DM plugin?", "DM plugin max_retry"],
      "questions_zh": ["DM plugin 的 batch_size 默认是多少?", "DM plugin 重试几次"],
      "confidence": 0.95
    },
    {
      "anchor": "DM Plugin Overview > How it connects to the Journey plugin",
      "heading_path": ["DM Plugin Overview", "How it connects to the Journey plugin"],
      "concepts": ["DM plugin and Journey plugin integration"],
      "keywords_raw": ["journey plugin", "integration", "adaptor"],
      "info_type": "how-to",
      "tier": "pointer-only",
      "fact_value": null,
      "pointer_to": "Journey Plugin page (see source) > Integration",
      "has_table": false,
      "has_image": false,
      "summary_en": "Says DM and Journey connect via the adaptor; details live on the Journey Plugin page.",
      "summary_zh": "说明 DM 与 Journey 通过 adaptor 衔接;细节在 Journey Plugin 页。",
      "questions_en": ["How does DM plugin connect to Journey plugin?"],
      "questions_zh": ["DM plugin 怎么和 Journey plugin 连接?"],
      "confidence": 0.6
    }
  ]
}
```

### 3.2 LLM prompt(逐 section 调用,英文)

> opencode 用代码切好 section 后,对每个 section 套这个 prompt 调 gpt-5.5。`heading_path` 和 `body_md` 由代码填入。`known_keywords` 是从词表读来的已审批规范名(可空)。

```
SYSTEM:
You extract a structured record from ONE section of a Confluence page, for building
a knowledge card index. Be faithful to the text — never invent facts, keywords, or values.

Return STRICT JSON with these fields:
{
  "concepts": [string],          // topics this section is about; prefer names from known_keywords if they match
  "keywords_raw": [string],      // keywords/aliases AS THEY APPEAR in the text (copy verbatim, include abbreviations)
  "info_type": one of ["what-is","how-to","config","troubleshoot","reference","decision","meeting-notes"],
  "tier": one of ["narrative","inline-value","pointer-only"],
  "fact_value": string|null,     // ONLY if tier=inline-value: the exact value(s), copied verbatim. Else null.
  "pointer_to": string|null,     // ONLY if tier=pointer-only: where the value actually lives. Else null.
  "summary_en": string, "summary_zh": string,   // one line each
  "questions_en": [string], "questions_zh": [string],  // 3–7 each; include >=1 keyword-style and >=1 natural-sentence
  "confidence": number           // 0..1, your confidence in this extraction
}

Rules:
- tier=inline-value ONLY when the section literally contains the precise value (number, code, error code, table cell).
  If the section merely says a value exists elsewhere, use tier=pointer-only and DO NOT fabricate the value.
- If the section is conceptual (definition/role/relationship), use tier=narrative.
- keywords_raw must be grounded in the text. Do not normalize or merge synonyms here — copy them as written.
- Keep exact identifiers (plugin/API/error/param names) intact; do not translate or rephrase them.

known_keywords (may be empty): {known_keywords}
heading_path: {heading_path}
section:
{body_md}
```

> 页面级 summary 节点的 prompt 直接复用 spec §6.2(`summary_en/zh` + 2–4 条 cross-cutting questions),此处不重复。

---

## 4. 硬规则 / guardrails(违反就会污染下游)

- **R1 — 三档诚实(最重要)**:有确切值才标 `inline-value` 并连出处放;没有就标 `pointer-only`。**绝不编一个像样的数值**。这条错了,答题 agent 会"自信地答错",而用户分不出来(见讨论稿 §6.3 ⚠️)。
- **R2 — 精确值原样搬**:`fact_value` 必须逐字摘录,不要改写、不要单位换算、不要"约等于"。表格不要从中间切。
- **R3 — 关键词照抄,不在 map 归一化**:`keywords_raw` 收原文所有叫法(含缩写 `DMP`)。"DMP = DM plugin"这种合并是 reduce 的活,map 越权合并会丢信息。
- **R4 — 不臆造关键词/概念**:`concepts` / `keywords_raw` 必须在正文有据。把页面塞不下的话题硬安上去,会污染倒排表。
- **R5 — 锚点必填**:每个 section 的 `anchor` 必须能定位回原文(`page_id` + `heading_path`)。给不出锚点的抽取等于没法 grounding,作废。
- **R6 — 不确定就降 `confidence` 并交给人**:模棱两可的 section(如这页到底算 config 还是 reference)给低分,reduce 会把低分项放进 review queue。**宁可标"我不确定",不要假装确定。**
- **R7 — 幂等**:同一页重跑要得到稳定结果;只有源页 `confluence_version` 变了才需要重跑(对应增量更新,讨论稿 §5.5)。

---

## 5. 已知 bad cases / 纠正规则(这一节会持续生长)

> **这是 SOP 自我进化的入口之一。** Business 评审或我们自己发现的错,提炼成规则写在这里,作为 few-shot 喂给 LLM / 作为代码规则。
> **纪律(防过拟合,见 SOP 主文档):** 能归纳成一条通用规则的,写成规则(下面"规则"区);只有规则说不清、必须靠例子的,才放原始 case(下面"few-shot"区)。不要把案例库里几十条原始 case 全部塞进 prompt——那样 prompt 会越来越长、还会过拟合。每条都在 `../../templates/bad_case_library_纠错案例库.md` 有对应记录。

### 5.1 规则(已从 bad case 提炼,直接执行)

- **[map-R-001] 缩写按别名处理,不新建概念。** 形如大写缩写(`DMP`、`OTP`)且语境靠近某全称时,放进该 section 的 `keywords_raw` 作为别名候选,**不要**单独造一个新 `concept`。是否等同交给 reduce + 词表 + Business 定。
  - 由来:bad case `map-001`(把 `DMP` 当成了独立于 `DM plugin` 的新概念)。
- **[map-R-002] "支持/可配置 X"不等于"X 的值"。** 句子只说"支持 retry 配置"而没给具体次数 → `tier=pointer-only`,不要标 inline-value、更不要编 `max_retry: 3`。
  - 由来:bad case `map-002`(把"支持 retry"误标成 inline-value)。

### 5.2 few-shot(规则说不清、靠例子)

```
(暂无。新增时:贴 section 原文片段 + 期望输出 JSON,并在 bad_case_library 里登记 case_id。)
```

---

## 6. 与其他文件的关系

- **读**:`../../templates/canonical_keywords_受控词表.md`(可选,用于复用规范名)。
- **写**:`outputs/map/map_<page_id>.json`(交给 reduce;同时是给 Business 看的中间产物之一)。
- **被改进**:bad case 经 `../../templates/bad_case_library_纠错案例库.md` 提炼后,更新本文件 §5。
- **上游规范**:切块/字段对齐 `RAG_PoC_Implementation_Spec.md` §4–§6;概念对齐 `Confluence_QA_PoC_方案讨论稿.md` §5–§6。
