---
name: card-reduce
description: >
  把所有 per-page map JSON 跨页合并成最终产物(reduce 阶段):①归一化关键词(把 DM plugin/
  Data Management/DMP 合并成一个规范概念,维护受控词表);②按规范概念汇总成卡片(card),
  narrative 字段可总结、精确字段顺锚点回原文原样取;③冲突按 version 取新并显式标注;
  ④产出 keyword→page 倒排表;⑤把存疑项放进 review queue 交 Business。当需要"把多页笔记
  汇总成按主题的卡片和索引"时使用本 skill。
---

# card-reduce —— 跨页合并 skill(给 opencode 读)

> 一句话:**把一堆"逐页笔记"(map JSON),按主题汇总成"卡片 + 索引",并把拿不准的挑出来给人看。**
> 中文为主;字段名 / JSON / SQL / prompt 一律英文。

---

## 0. 给初学者:reduce 在做的三件事

```
  所有 map_*.json ──►  [card-reduce]  ──┬──►  canonical_keywords(受控词表,会长大)
   (逐页笔记)                            ├──►  cards(每个主题一张卡片)
                                         ├──►  keyword→page 倒排表(association)
                                         └──►  review_queue(存疑项,给 Business 审)
```

1. **归一化(normalize)**:同一个东西在不同页有不同叫法(`DM plugin` / `Data Management plugin` / `DMP`)。reduce 要把它们认成**同一个概念**,起一个**规范名(canonical name)**,其余记成**别名(aliases)**。
   - ⚠️ **这是整套方案最容易塌的一步。** 不做归一化,倒排表会按叫法碎成好几块,召回直接掉。
2. **合并成卡片(merge)**:把指向同一概念的所有 section,按"卡片模板"汇总成一张卡片;每个字段标好三档(narrative/inline-value/pointer-only)和锚点。
3. **挑出存疑项(flag)**:拿不准的合并、冲突的数值、低置信度、新冒出来的 topic —— 全部进 `review_queue`,**不偷偷替人做决定**,交给 Business。

> **关键背景:词表是产物,不是输入。** 原方案设想 Business 给受控词表;既然给不了,**词表由 map 自报关键词 → reduce 归一化自底向上长出来,Business 只审批**。所以词表里的新词初始 `status=proposed`,审批后才 `approved`(见 SOP 主文档"角色分工")。

---

## 1. 输入

- `outputs/map/map_*.json`:切片内**所有页**的 map 产物(全量,别只取业务点名的页)。
- `../../templates/canonical_keywords_受控词表.md`:**当前**受控词表(可能为空;第一次跑就是从空开始长)。
- `../../templates/card_template`(卡片模板):见 §4。第一版用本 skill 自带的默认模板,Business 可调整。
- 既有冲突/锚点规范对齐 `Confluence_QA_PoC_方案讨论稿.md` §5.2、§5.6、§6.2。

---

## 2. 步骤

### Step 1 — 归一化关键词,更新受控词表(最关键)

1. 收集所有 map JSON 里的 `keywords_raw` 和 `concepts`,得到一个"原始叫法"的大清单。
2. **先用现有词表对齐**:能匹配到已审批 `canonical_name`/`aliases` 的,直接归到那个 `canonical_id`。**不要给已有概念另起新规范名**(幂等的关键)。
3. 剩下没匹配上的,用 §3.1 的 prompt 让 gpt-5.5 **聚类**:把指向同一事物的叫法聚成一簇,给一个 `canonical_name`,其余作 `aliases`,初始 `status=proposed`。
4. **拿不准的合并 → 不要硬合,进 `review_queue`**。例如 `OTP` 到底指 "MDC OTP Service" 还是泛指一次性密码?标出来让 Business 定。
5. 把新概念 / 新别名写回 `canonical_keywords_受控词表.md`(`proposed`)。Business 审批后改 `approved`;判错的别名经 bad case 流程改 `merged`/`deprecated`。

> **防过拟合提示**:别为每个细微变体都造一个新 canonical。规范名应对应"用户心里的一个东西"。粒度问题拿不准时,宁可合并 + 在卡片里留子条目,也别让词表爆炸。

### Step 2 — 按规范概念合并成卡片(card)

对每个 `canonical_id`,把所有指向它的 section 汇总成一张卡片,按模板(§4)填字段。每个字段都带:`tier`、`anchor`、`source_url`、`confluence_version`。

- **narrative 字段(定义/功能/关系)**:可由 LLM 把多页 narrative **总结合并**。
- **精确字段(config/错误码/表格/代码)**:**顺锚点回原文原样取(grounding),不要"总结的总结"**。也就是卡片里存的精确值,要么是从原文逐字搬来的 `inline-value`,要么干脆只留 `pointer-only` 指回原文——**绝不允许把已经总结过的页摘要再总结一遍**(两次有损压缩,精确值必丢,对应讨论稿 §5.2)。
- **关系字段**:用"相关组件"做**软链接**(记 `canonical_id`),PoC 阶段不做全量实体归并。

### Step 3 — 冲突处理(取新 + 显式标注)

同一字段在多页/多版本不一致时(典型:旧页 `batch_size=500`,迁移页改成 `1000`):

- 按 `confluence_version` / `update_at` **取新**的作为 `authoritative=true`。
- **必须显式标注冲突**(`conflict=true` + 列出各来源各值),**不让 LLM 悄悄挑一个**。
- 冲突项**同时进 `review_queue`**,让 Business 确认哪个才对(有时新页是错的)。

### Step 4 — 产出 keyword→page 倒排表(association)

把"每个 canonical 概念 → 它出现在哪些 page/anchor"建成倒排表。它一物两用(讨论稿 §5.3):
- **给 Business 当审核界面**:不必重读文档,只看"这个关键词关联到了哪些页",一眼挑出关联错的(精度)和该在却没在的页(召回)。
- **反向发现漏列 topic**:在多页反复出现、却还没成卡片的词簇 = 候选新卡片。

### Step 5 — 产出 review_queue(交给 Business)

凡符合下列任一,进队列(对应 `../../templates/business_review_checklist_评审清单.md`):
- 归一化拿不准的合并;
- 冲突值;
- section `confidence` 低于阈值(默认 < 0.6);
- 新冒出来、不在词表里的高频 topic;
- 某卡片关键精确字段只有 `pointer-only`(可能需要补抓原文)。

### Step 6 — 落库 / 落盘

- 卡片 + 倒排表既是给人看的中间产物(markdown/JSON),也按 spec §7 的表结构入 pgvector(`refs`/`descriptions`/`summaries`,卡片可作为 description/summary 节点)。
- **幂等**:某页 `version` 变 → 只重跑该页 map → 只对受影响的 `canonical_id` 重做 reduce,不全量重算(讨论稿 §5.5)。

---

## 3. 输出 schema + LLM prompt

### 3.1 归一化(聚类)prompt(英文)

```
SYSTEM:
You are normalizing keyword variants into canonical concepts for a knowledge base.
Given a list of raw keyword strings (collected verbatim from many pages) and the list of
already-approved canonical concepts, do the following and return STRICT JSON.

1) Map each raw keyword to an existing canonical_id if it clearly refers to the same thing.
2) Cluster the remaining raw keywords: each cluster = one concept. Pick a canonical_name
   (the clearest full form) and list the rest as aliases.
3) If a keyword is AMBIGUOUS (could belong to two concepts, or you are unsure), DO NOT force a
   merge — put it in "needs_review" with a short reason.

Return:
{
  "mapped":   [{"raw": "...", "canonical_id": "..."}],
  "new":      [{"canonical_name": "...", "aliases": ["..."], "example_raw": ["..."]}],
  "needs_review": [{"raw": "...", "reason": "..."}]
}

Rules:
- Treat uppercase abbreviations near a full name as alias candidates, not new concepts (e.g. "DMP" ~ "DM plugin").
- Do not invent concepts not present in the raw list.
- Prefer fewer, well-scoped concepts over many near-duplicates.

approved_canonicals: {approved_canonicals}
raw_keywords: {raw_keywords}
```

### 3.2 卡片(card)JSON schema

```json
{
  "canonical_id": "C-0007",
  "canonical_name": "DM Plugin",
  "aliases": ["Data Management plugin", "DMP"],
  "component": "DM",
  "status": "proposed",                     // proposed → approved(Business 审批后)
  "fields": [
    {
      "field": "definition",
      "tier": "narrative",
      "value": "把消息投递到各渠道的插件,是投递链路的核心组件。",
      "sources": [
        {"page_id": "123456", "anchor": "DM Plugin Overview > What is the DM Plugin",
         "source_url": "https://confluence/.../DM-Plugin-Overview", "confluence_version": 7}
      ]
    },
    {
      "field": "config",
      "tier": "inline-value",
      "value": "batch_size: 1000; max_retry: 3",
      "authoritative": true,
      "conflict": true,
      "conflict_detail": [
        {"value": "batch_size: 500",  "page_id": "123456", "confluence_version": 7,  "update_at": "2026-05-20"},
        {"value": "batch_size: 1000", "page_id": "777001", "confluence_version": 3,  "update_at": "2026-05-28"}
      ],
      "sources": [
        {"page_id": "777001", "anchor": "SFMC Migration > DM Plugin Config",
         "source_url": "https://confluence/.../SFMC-Migration", "confluence_version": 3}
      ]
    },
    {
      "field": "timeout_config",
      "tier": "pointer-only",
      "value": null,
      "pointer_to": "DM Plugin Overview > Configuration (timeout 行未给具体值)",
      "sources": [
        {"page_id": "123456", "anchor": "DM Plugin Overview > Configuration",
         "source_url": "https://confluence/.../DM-Plugin-Overview", "confluence_version": 7}
      ]
    },
    {
      "field": "related_components",
      "tier": "narrative",
      "value": "经 adaptor 与 Journey Plugin 衔接。",
      "soft_links": ["C-0008"],                 // Journey Plugin 的 canonical_id
      "sources": [
        {"page_id": "123456", "anchor": "DM Plugin Overview > How it connects to the Journey plugin",
         "source_url": "https://confluence/.../DM-Plugin-Overview", "confluence_version": 7}
      ]
    }
  ],
  "flags": ["alias 'DMP' 待 Business 确认", "config 字段存在版本冲突"]
}
```

### 3.3 keyword→page 倒排表(一行一个 page/anchor 关联)

```json
{"canonical_id": "C-0007", "canonical_name": "DM Plugin",
 "page_id": "123456", "anchor": "DM Plugin Overview > Configuration",
 "info_type": "config", "tier": "inline-value", "confidence": 0.95, "confluence_version": 7}
```

### 3.4 review_queue item

```json
{"queue_id": "RQ-0012", "type": "conflict",
 "canonical_id": "C-0007", "field": "config",
 "detail": "batch_size: v7 页=500 vs v3 页=1000;已暂取 1000(取新),请确认哪个对。",
 "options": ["500 (page 123456)", "1000 (page 777001)"], "status": "open"}
```

---

## 4. 卡片模板(card template,默认版;Business 可调)

> 来自讨论稿 §5.6。**原则:字段由"用户会问什么"倒推,必须含精确事实字段,不能只有定义/功能。** 可按 `content_type` 设多套模板 + 一个 catch-all 字段兜底。

| 字段 field | 说明 | 来源策略(tier) |
|---|---|---|
| `definition` | 这是什么 | narrative,可总结 |
| `responsibility` | 干嘛的 / 职责 | narrative,可总结 |
| `config` | 配置项,逐项含默认值/取值范围 | **inline-value,回原文原样取** |
| `interface_deps` | 依赖谁、被谁依赖 | 半精确,带锚点 |
| `related_components` | 与其他组件的关系(喂"how X and Y work together") | narrative + soft_link |
| `troubleshoot` | 常见问题 / 坑 | 带锚点 |
| `catch_all` | 模板没覆盖但重要的点 | 视情况 |
| `anchors` | 每个字段都必须能指回原文 | 必填 |

---

## 5. 硬规则 / guardrails

- **G1 — 归一化优先复用,不重造规范名**:能归到已有 `canonical_id` 就归,保证幂等。
- **G2 — 拿不准不硬合**:模糊的合并进 `review_queue`,不替 Business 拍板。
- **G3 — 精确字段只 grounding,不做"总结的总结"**:inline-value 逐字来自原文;否则降级 pointer-only。违反 = 精确题答错的主因。
- **G4 — 冲突必标**:取新的同时永远写明 `conflict_detail`,并进队列。**不允许悄悄选一个**。
- **G5 — 一切 claim 带锚点**:卡片每个字段都要能点回原文,否则下游无法 grounding。
- **G6 — 新概念默认 `proposed`**:未经 Business 审批的概念/别名不得标 `approved`。
- **G7 — 幂等增量**:页变只重算受影响概念,结果稳定可复现。

---

## 6. 完整走查示例(强烈建议照着理解一遍)

**输入:两页的 map 产物(节选)**

- `map_123456.json`(页:DM Plugin Overview,version 7,2026-05-20):
  - section A `concepts=["DM plugin"]`, `keywords_raw=["Data Management plugin","DM plugin","DMP"]`, `tier=narrative`(定义)
  - section B `keywords_raw=["batch_size","max_retry"]`, `tier=inline-value`, `fact_value="batch_size default 500; max_retry: 3"`
  - section C `keywords_raw=["journey plugin","adaptor"]`, `tier=pointer-only`, `pointer_to="Journey Plugin page"`
- `map_777001.json`(页:SFMC Migration,version 3,2026-05-28):
  - section X `keywords_raw=["DMP","batch_size"]`, `tier=inline-value`, `fact_value="batch_size: 1000"`

**reduce 处理:**

1. **归一化**:`DM plugin` / `Data Management plugin` / `DMP` → 一个概念 `C-0007 DM Plugin`(`DMP` 是缩写,按别名候选,但**初始 proposed + 进 review_queue 让 Business 确认**)。
2. **合并卡片**:
   - `definition` ← section A 的 narrative。
   - `config` ← section B(500)和 section X(1000)**冲突** → 取新(777001 的 `update_at` 更晚)→ `value=batch_size:1000`,`authoritative=true`,`conflict=true` + 列两个来源;进 `review_queue`(RQ-0012)。
   - `related_components` ← section C,`soft_link → C-0008(Journey Plugin)`。
3. **倒排表**:`C-0007` 关联到 page 123456(anchor A/B/C)和 page 777001(anchor X)。
4. **review_queue**:① 别名 `DMP` 待确认;② config 冲突待确认。

**输出** = §3.2 的那张卡片 JSON + §3.3 的几条倒排记录 + §3.4 的队列项 + 词表里新增一行 `C-0007`(proposed)。

> 看懂这个例子,你就理解了 reduce 的全部精髓:**认同一个东西(归一化)→ 按主题汇总(卡片)→ 精确值回原文(grounding)→ 不一致就摆出来(冲突)→ 拿不准交给人(队列)。**

---

## 7. 已知 bad cases / 纠正规则(持续生长)

> 纪律同 map skill §5:能成规则就写规则,规则说不清才放原始 case;每条对应 `../../templates/bad_case_library_纠错案例库.md` 一个 `case_id`。

### 7.1 规则(已提炼)

- **[reduce-R-001] 数值冲突一律取新 + 标注 + 进队列。** 禁止静默选值。
  - 由来:bad case `reduce-001`(batch_size 冲突时取了旧值且没标注)。
- **[reduce-R-002] 缩写别名先 proposed,不直接 approved。** 缩写归并即便看着对,也要过 Business 一道。
  - 由来:bad case `map-001`(DMP 缩写场景:缩写别名应先 proposed,过 Business 再 approved)。

### 7.2 few-shot

```
(暂无。新增时:贴几条 map 输入 + 期望的归一化/卡片片段,并在 bad_case_library 登记。)
```

---

## 8. 与其他文件的关系

- **读**:`outputs/map/map_*.json`(map 产物)、`../../templates/canonical_keywords_受控词表.md`(当前词表)。
- **写**:`outputs/cards/*.json`(卡片)、`outputs/inverted_index.jsonl`(倒排表)、`outputs/review_queue.jsonl`(给 Business)、并回写词表新行(proposed)。
- **被改进**:bad case 经案例库提炼后更新本文件 §7、卡片模板 §4、或词表。
- **上游规范**:`RAG_PoC_Implementation_Spec.md` §6–§7;`Confluence_QA_PoC_方案讨论稿.md` §5–§6。
