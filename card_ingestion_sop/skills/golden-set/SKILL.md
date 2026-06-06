---
name: golden-set
description: >
  在 card store 建好之后,生成一套**冻结的 golden 评测集**,用来客观对比三族回答方式
  (RAG / LLM+Wiki卡片 / Agentic)。题目由 LLM 生成,但**gold 标注来自留出的原文页、不是卡片**,
  且用与索引/卡片不同的 prompt(解耦),否则 recall/association_recall 会虚高。覆盖 5 类题型 + 多 module,
  人工抽检 ~20%,冻结成 golden_set.json。当需要"为评测准备标准答案题库"时使用本 skill。
---

# golden-set —— 评测题库生成 skill(给 opencode 读)

> 一句话:**card store 建好后,出一套"考卷+标准答案",而且标准答案来自原文、不是来自我们自己生成的卡片。**
> 何时跑:`ingest → map →(同事词表)→ reduce → load`(card store + refs 已就绪)**之后**。
> 中文为主;字段名 / JSON / prompt 一律英文。

---

## 0. 给初学者:为什么"card store 之后"跑,但 gold 不能来自卡片

- **触发时机**是 card store 之后——因为这时"被测系统"(卡片 + 检索)才完整,能跑三族对比。
- **但 gold(标准答案)必须来自原文(留出页),不是卡片。** 这是头号红线(spec §11.1):
  - 如果用卡片/索引问题来出题、用卡片来定 gold,就等于"拿系统自己的产物考自己",recall、`association_recall` 全部虚高,评测失去意义。
  - 正确做法:题目模仿真实用户问法(另一套 prompt),gold 指向**原始 Confluence section**(`page_id#heading`)。card store 只用来**挑难题位置**(见下),不用来定答案。

```
card store 就绪 ──► [golden-set]
                      │  题目: LLM 用"真实用户口吻" prompt 生成(与索引/卡片解耦)
                      │  gold:  指向留出原文 section,人工抽检 20%
                      ▼
                 golden_set.json(冻结 + frozen_hash)──► eval harness 跑三族
```

---

## 1. 输入 / 输出

**输入:**
- 留出的**原文**:`outputs/capture/*.json` 或 `outputs/loaded_refs.json`(section 正文 + `section_id` + `module`)。**这是 gold 的唯一来源。**
- `module` facet(每个 section/页带):用于覆盖均衡 + 产出 per-module 评测。
- (仅用于"挑难题位置",不定 gold)card store:`outputs/cards/*.json`——找出哪些 topic 的字段是 `pointer-only`,据此构造 `pointer-drill` 漏钻题。
- (可选)同事的 keyword_table:用其 `module` 列保证题目覆盖各业务域。

**输出:**
- `outputs/golden_set.json`:冻结题库 + `frozen_hash`(schema 见 §3.1)。
- `outputs/golden_human_check.md`:随机 ~20% 待人工抽检清单。

---

## 2. 步骤

### Step 1 — 选材(留出原文)
从 `loaded_refs` / `capture` 取 section 正文。**只用原文**;不要读 `outputs/map/*` 里生成的 `questions_*`、也不要读卡片字段当题面/答案来源。按 `module` + `component` 分层,保证覆盖均衡。

### Step 2 — 出题(调 gpt-5.5,§3.2 解耦 prompt)
用**与 map/card 不同**的 prompt,模仿真实用户:口语、关键词式、有时含糊、中英双语。**不要**工整的 "What is X"(那是索引问题的风格)。

### Step 3 — 5 类题型 + 默认配比(共 ~50)
| 类型 | 测什么 | gold |
|---|---|---|
| `single` (~35%) | 单段可答 | 1 个 section |
| `multihop` (~15%) | 跨段综合("X 和 Y 怎么配合") | **多个** section |
| `identifier-lookup` (~25%) | 精确值/错误码/默认值 | 含值的 section |
| `pointer-drill` (~15%) | 卡片只有指针、真值在别处 → 测**下钻/漏钻** | 真值所在 section |
| `out-of-scope` (~10%) | 文档没有 → 测**拒答** | `"NO_ANSWER"` |

> `pointer-drill` 的题用 card store 来"挑位置":找 `tier=pointer-only` 的字段 → 就那个 topic 出一道精确题 → gold 标到**原文里真正含值的 section**(不是卡片)。

### Step 4 — 标注
每题:`gold_section_ids`(`page_id#heading`,越界题=`"NO_ANSWER"`)+ `gold_answer`(简短参考答案)+ `type` + `module`(可选,便于 per-domain 评测)。section-id 口径与检索结果一致(见 `fixtures/README.md` 约定)。

### Step 5 — 人工抽检 ~20%
随机抽 20% 写进 `golden_human_check.md`:核对"问题是否真实、gold section 是否真能答"。抽检过的标 `human_checked=true`。LLM 出的 gold 会有错,不抽检指标带噪。

### Step 6 — 冻结
计算 `frozen_hash`(对题目内容做 sha256),写 `golden_set.json`。**所有变体/所有 run 跑同一份冻结集**,才能 apples-to-apples。改题=新版本+新 hash。

---

## 3. 输出 schema + prompt

### 3.1 golden_set.json
```json
{
  "frozen_hash": "sha256(...)",
  "items": [
    {"q_id": "G-001", "q_en": "...", "q_zh": "...",
     "type": "single|multihop|identifier-lookup|pointer-drill|out-of-scope",
     "gold_section_ids": ["123456#Configuration", "..."],   // 越界题用字符串 "NO_ANSWER"
     "gold_answer": "...", "module": ["Integration & API standard"], "human_checked": true}
  ]
}
```
> 与 `fixtures/golden_seed/golden_seed.jsonl` 同构(多了可选 `module`),codex 的 `eval/golden_gen.py` 直接产这个。

### 3.2 出题 prompt(英文,务必与索引/卡片解耦)
```
SYSTEM:
You write realistic test questions to EVALUATE a documentation QA system. Write as a busy
engineer would actually type — terse, keyword-y, sometimes vague — NOT polished prose, and
DO NOT imitate the style of indexed/card questions. Use ONLY the provided source section(s);
never invent facts. Bilingual (en + zh).

For each item return STRICT JSON:
{ "q_en","q_zh","type"(single|multihop|identifier-lookup|pointer-drill|out-of-scope),
  "gold_section_ids":[ "<page_id>#<heading>", ... ] or "NO_ANSWER",
  "gold_answer":"...", "module":[...] }

Rules:
- gold_section_ids must point to the SOURCE sections that actually answer it (not cards).
- identifier-lookup → the section that literally contains the value.
- multihop → list ALL needed sections.
- out-of-scope → ask something the corpus does NOT cover; gold_section_ids = "NO_ANSWER".
- Keep exact identifiers (param/error/plugin names) intact.

source_sections (held out; gold must come from here):
{sections}     # each: {section_id, heading_path, module, body_md}
```

---

## 4. 硬规则 / guardrails
- **G1(红线)gold 来自原文,不来自卡片/索引问题。** 触发时机是 card store 之后,但答案来源是留出原文。
- **G2 解耦 prompt**:出题 prompt ≠ map/card 的 prompt;口吻像真实用户。
- **G3 冻结**:`frozen_hash` 锁定;所有变体同一份。
- **G4 抽检**:≥20% 人工核 `human_checked`。
- **G5 必含 `out-of-scope`**(测拒答)和 `pointer-drill`(测漏钻),否则三族对比测不出关键差异。
- **G6 覆盖均衡**:按 `module`/`component` 铺开,避免只考某一块。
- **G7 section-id 口径**与检索返回一致(`page_id#heading`),否则 recall 算不出。

---

## 5. 走查示例(用 fixtures)
- `identifier-lookup`:"dm 默认重试几次" → gold `123456#Configuration`,ans "3"。(card 里该字段可能 inline,但 gold 仍指原文)
- `pointer-drill`:card store 显示 DM 的 retry 字段在排障页是 `pointer-only` → 出"dm 超时/重试怎么配" → gold 指**原文** `123456#Configuration`(真值处),测 agent 会不会下钻。
- `multihop`:"DM 和 journey 怎么配合" → gold `[123456#How it connects to the Journey Plugin, 220110#Receiving from DM, 140020#What is the Adaptor]`。
- `out-of-scope`:"DM 支持发短信吗" → `"NO_ANSWER"`。

---

## 6. 与其他文件的关系
- **下游**:`eval/golden_gen.py` 实现本 skill;`eval/service.py` 用 `golden_set.json` 跑三族变体(`01_CODEX_构建规格.md` §6)。
- **规范**:解耦红线 `RAG_PoC_Implementation_Spec.md` §11.1;指标(recall@k / faithfulness / `association_recall` / `漏钻率`)§11.2 与讨论稿 §8。
- **回归集区分**:本 golden 测"效果";`bad_case_library` 的回归集测"skill 行为",两套别混(SOP §7)。
- **起步集**:`fixtures/golden_seed/golden_seed.jsonl` 是 15 题离线起步;本 skill 在真实数据上扩到 ~50 并冻结。
