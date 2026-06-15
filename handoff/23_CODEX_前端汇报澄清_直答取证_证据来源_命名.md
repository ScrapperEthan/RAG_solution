# 23 CODEX 前端规格：汇报澄清 pass（直答/取证 + 证据来源 + 去重命名）

**给 codex（外网仓库 `frontend/`）。claude 写规格，codex 实现，claude review。**

> 定位：**不是重构，是"讲解就绪(汇报级)的澄清 pass"**。三族（Agentic / RAG / 卡片库）+ 评估看板的骨架是对的、与 `eval` 对齐、**不要动结构**。只做"让 Ethan 和观众一眼看懂"的事：解释直答/取证、把证据来源标到台面、消除一个撞名。

## 0. 背景（为什么做）
当前痛点不是功能缺失，是**自解释性差**：
1. `index.html` 里「LLM + Wiki」族下的子模式 `卡片直答 / 卡片+回原文取证`（`<select id="cardModeSelect">`，[index.html:80-86](../frontend/index.html)）**只有干巴选项、没解释**，差别只在答完后才隐约看得到。
2. 回答结果里其实带了 `execution.evidence_kind`（`card|source|retrieval|none`）和 `drilled`，**这是 grounding/可追溯的"汇报金句"，但前端没把它显著标出来**。
3. 族名「LLM + Wiki」和外部开源项目 `llm-wiki-agent` **撞名**，容易让人（含 Ethan 自己）误会两者有关。这里的 "Wiki" 其实就是**本系统的审批卡片库**。

## 1. 现状（复用，别重写）
- 纯静态 + FastAPI 挂载；vanilla JS + `style.css` CSS 变量，**不引入框架/打包工具**。
- `frontend/app.js` 关键事实（**改名前必读，避免改坏**）：
  - 内部族键：`state.answerFamily ∈ {"agentic","rag","llm-wiki","llm-direct"}`，由 DOM 上的 `data-answer-family="..."` 驱动（[app.js:49-50,179-182](../frontend/app.js)）。
  - `selectedAnswerMode()`：`rag→"pure-rag"`、`llm-wiki→el("cardModeSelect").value`（即 `card-direct`/`card-grounding`）、`llm-direct→"llm-direct"`、其余 `agentic`（[app.js:188-190](../frontend/app.js)）。
  - 显示文案在 COPY 对象里：`ANSWER_FAMILY_COPY`/同类（[app.js:30-31,449,596](../frontend/app.js)）。
- 回答契约：`POST /api/chat/stream`，body `{query, answer_mode, language, module}`；NDJSON，逐行 `token`，末行 `{"type":"result","result":{...execution...}}`（schema 见 `handoff/21` §3.2）。

## 2. 任务清单

### A. 解释「卡片直答 vs 卡片+回原文取证」（index.html）
在 `<label id="cardModeField">`（[index.html:80-86](../frontend/index.html)）下方加一个**随选择实时更新**的说明块（`<small id="cardModeHint">`），文案：
- `card-direct`（卡片直答）：**"答案直接取自卡片里 reduce 已提炼的字段值，不回原文。快、像查词条；精确值受卡片保真度限制。"**
- `card-grounding`（卡片+回原文取证）：**"卡片只用来定位主题，答案回到 Confluence 原文段落由 LLM 重新生成，可逐句追溯。适合精确值/有争议的问题。"**

参考依据（给 codex 对照，**不要写进 UI**）：后端两条路径在 [backend/agentic/service.py:100-123](../backend/agentic/service.py)（`answer_from_card` vs `refs_for_card→answer_from_refs`）。

### B. 把"证据来源"标到台面（index.html / app.js · **汇报核心**）
回答后，在「执行轨迹/回答与执行轨迹」区顶部显著渲染两枚徽标，数据取自 `result.execution`：

| `evidence_kind` | 显示文案（徽标） | 配色建议 |
|---|---|---|
| `card` | 证据来源：**卡片字段**（未回原文） | 绿/accent |
| `source` | 证据来源：**原文段落**（已回原文取证） | 蓝 |
| `retrieval` | 证据来源：**全库检索**（RAG，未经卡片） | 灰 |
| `none` | **无可验证证据** | 红/警告 |

并同排显示 `是否回原文：是/否`（来自 `result.execution.drilled` 或 `result.drilled`）。这一步让"我们的答案能不能追溯到原文"对观众**一眼可见**——是这次澄清最重要的产出。

### C. 去重命名（消除与 `llm-wiki-agent` 撞名）— 推荐做
把**所有人类可见**的「LLM + Wiki」字样改为 **「卡片库（审批卡）」**：
- index.html 族按钮（[index.html:73-75](../frontend/index.html)）的 `<strong>` 文案、`answerSourceLabel`、子模式标题等可见文字。
- app.js COPY 字符串（[app.js:30,449,596](../frontend/app.js)）里的 `"LLM + Wiki…"` 显示文本。

> ⚠️ **硬约束（改坏即回滚）**：**只改人类可见文案**。绝不改：
> - `data-answer-family="llm-wiki"`（属性值/内部族键，app.js 全靠它）；
> - `cardModeSelect` 的 option **value**（`card-direct` / `card-grounding`）；
> - 发给 API 的 `answer_mode` 字符串；元素 `id`。

### D. 每页"唯一职责"一句话（轻量对齐）
- `index.html`：已有"这是什么页"提示（[index.html:36-39](../frontend/index.html)），保留，可微调为：**"主问答页：同一问题在 基线 / RAG / 卡片库 三族下的回答 + 执行轨迹(思维链)。"**
- `cards.html`：已有清晰说明（[cards.html:176-181](../frontend/cards.html)），其提问框**确实会出答案**，所以把按钮/提示语对齐为"**演示一次回答的下钻路径**"，不要暗示它是第二个问答引擎。改动**极小**。

## 3. 目标叙事（codex 不实现，仅作为对齐"改完长啥样"）
汇报时三步走，每页一句话职责：
1. **index.html 实时问答** → 选一个 Golden 问题，依次切 `模型直答(基线) → RAG → 卡片库(直答/取证)`，每次都指着 B 步的「证据来源」徽标说"看，这条能/不能追溯原文"。
2. **评估看板** → 三族横向指标，量化"卡片库 + grounding"的价值。
3. **cards.html 卡片库** → 展示一张卡的 topic→subsection→fact→引用，讲"人工冻结闸"的治理价值，并用提问框走一条下钻高亮路径。

## 4. 验收清单
- [ ] 切换 `卡片直答/卡片+取证` 时，下方说明文案实时更新且准确。
- [ ] 回答后，「证据来源」徽标按 `evidence_kind` 正确显示四态之一 + `是否回原文`。
- [ ] 「LLM + Wiki」可见文案全部改为「卡片库（审批卡）」；**`data-answer-family`/`answer_mode`/option value/id 一字未动**；三族切换、子模式显隐、提交回答全部照常工作。
- [ ] `pure-rag`（无卡片）和 `llm-direct`（无 grounding）路径下，证据来源分别显示"全库检索 / 无可验证证据"，不报错。
- [ ] 纯静态、无新依赖、复用 `style.css`；无任何硬编码内网数据。

## 5. 硬规则
- **不重构结构**，不动 `app.js` 的族/模式路由逻辑（只改 COPY 文案 + 加证据徽标渲染 + cardModeHint）。
- 不改 backend；若发现需要后端补字段，写到 `handoff/` 新文件由 claude 来加，**不要自己改 backend**。
- 回报：改动 diff + 三族各一张截图（用脱敏/Golden，不贴真实内网数据）。
