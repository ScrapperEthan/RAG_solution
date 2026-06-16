# 30 卡片 drilldown 失败 → 回退 RAG：后端契约变更 + 召回链路两段式渲染（给 codex）

**claude 已在外网改完后端并加回归测试（104 tests OK）。本篇给 codex：后端 `execution` / `debug` 契约新增了"两段式"形态，handoff 29 的召回链路可视化要能渲染它。** 日期：2026-06-16。

## 1. 背景（一句话）
卡片命中后走 drilldown（回原文取证）时，如果该卡声明的 source sections **不含答案**，旧逻辑直接 `NO_ANSWER` 死路一条——而同一个问题 **pure-rag 能答上来**。即"开了卡片反而比纯 RAG 更差"。现已修复：**卡片先全精度试答；只有结果是 NO_ANSWER 时，才回退到 hybrid RAG。** 卡片能答时 RAG 完全不介入（确定性/可审计不被稀释）。

> 注意：是 **NO_ANSWER 才回退**，不是"把卡片 refs 和 RAG 召回 merge"。后者会把版本混乱的 chunk 重新塞回 LLM，毁掉卡片的精确锁值——已明确否决。

## 2. 后端实际改动（`backend/agentic/service.py`）
- 三处 drilldown 站点（`card-grounding`、`agentic` 的 exact-no-inline、`agentic` 的 pointer-only）合并进新方法 `_drilldown_with_fallback(...)`。
- 触发判据 = 顶层新函数 `is_no_answer(answer)`：`answer` 文本 strip 后大写以 `NO_ANSWER` 开头。**它同时覆盖两种失败**：refs 为空（卡片啥都没声明）、refs 非空但不含答案（卡片声明了错的 section——这是 Ethan 实际踩的那种）。
- 回退用的检索与"完全没命中卡片"那条兜底一致：`index="both", search="hybrid", top_k=8, rerank=variant.rerank, filters=filters`。
- 回归测试：`backend/tests/test_agentic_drilldown.py::DrilldownFallbackTest`（命中→不碰 RAG；NO_ANSWER→回退且 trace 留痕）。

## 3. 契约变更（codex 必读）—— `execution` 与 `debug`
当回退发生时，返回结构与"单段卡片取证"不同：

| 字段 | 单段（卡片取证成功，旧形态） | 两段（卡片失败→回退 RAG，新形态） |
|---|---|---|
| `execution.path` | `card-grounding` / `agentic-source-drilldown` | **`card-grounding-then-rag-fallback`** / **`agentic-source-drilldown-then-rag-fallback`** |
| `execution.evidence_kind` | `source` | **`retrieval`** |
| `execution.steps` | 卡片取证步骤 | 卡片取证步骤 **+ `Card drilldown returned NO_ANSWER` + `Fallback to hybrid RAG retrieval`** |
| `execution.card` | 命中的卡 | **仍是命中的卡**（保留"试过哪张卡"） |
| `debug.drilldown` | 卡片下钻明细 | **仍在**：是"试了但没答出来"的那次卡片下钻（`resolved/missed/counts`） |
| `debug.retrieval` | `null` | **被填充**：真正答出答案的 RAG 命中 |
| `debug.refs_used` | 卡片 refs | **RAG refs**（真正喂给 LLM 出答案的那批） |

**关键差异**：以前 `debug.drilldown` 与 `debug.retrieval` 是**互斥**（要么卡片路径要么 RAG 路径，另一个为 `null`）。**现在回退态下两者会同时非空**——`drilldown` 是"失败的卡片尝试"，`retrieval` 是"救场的 RAG"。handoff 29 的渲染若假设了"二选一"，需要放开。

## 4. codex 要做的（召回链路可视化，handoff 29 域内）
把回退态渲染成**两段链路**，让"卡片试过→没答上→RAG 救场"这个故事一眼可读：
1. **第一段（卡片）**：照常画 routing(命中哪张卡) + drilldown(`gathered/resolved/missed/capped_to`)，但**标注为"已尝试，返回 NO_ANSWER"**（建议置灰/加删除线/加 ⚠ 徽标），因为它没产出最终答案。
2. **第二段（RAG 回退）**：画 `debug.retrieval.hits`（即真正出答案的来源），并用 `execution.steps` 里那两条新步骤把两段衔接起来。
3. **顺手做个信号面**：**回退发生 = 这张卡 source 建漏了**（命中了卡但卡里没有答案的那一节）。可在卡片那段打个"该卡覆盖不全"的徽标——这正是 Ethan 排查"哪些卡要补 source"的入口，别让它被 RAG 救场后悄无声息。
4. 判定回退态：`execution.path` 以 `-then-rag-fallback` 结尾，或 `debug.drilldown` 与 `debug.retrieval` 同时非空。

## 5. 验收
- 选一个"卡片命中但该卡不含答案"的 Golden（agentic 或 card-grounding 模式 + Debug）：
  - 最终答案来自 RAG（**不再是 NO_ANSWER**）；
  - 召回链路面板**同时**显示：①失败的卡片下钻（标注 NO_ANSWER/覆盖不全）②救场的 RAG 命中；
  - `execution.steps` 末尾出现那两条衔接步骤。
- 卡片本身能答的 Golden：链路仍是**单段**卡片取证，`debug.retrieval` 为 `null`，行为与改动前一致（无回归）。

## 6. 不在本次范围（避免误解）
- **`agentic-card-direct`（卡片直答字段值，不下钻）返回 NO_ANSWER 时不回退**——那是另一条路径、另一类成因，本次只修"下钻取证"三站点。若要让 agentic 模式彻底无死路，是单独一轮（见给 Ethan 的 31 篇 §4）。
- 后端已 push 前请 Ethan 确认；codex 改前端可基于本契约先行。
