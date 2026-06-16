# 32 tag 兄弟卡横跳 + tag 加权 RAG：链路渲染补充（给 codex）

**claude 已在外网把回退链从两段扩成"卡片 → 同 tag 兄弟卡 → tag 加权 RAG"，并加测试（110 tests OK）。本篇给 codex：`execution` / `debug` 又多了一种形态，handoff 30 的两段式渲染要再认两个新 `path`。** 日期：2026-06-17。

## 1. 背景（一句话）
卡片下钻 NO_ANSWER 后，**先横跳到与命中卡共享 tag(module) 的"兄弟卡"**再答；兄弟卡也答不上才掉 RAG，且这次 RAG 用原卡的 module 做**软加权**（boost，不排他）。`module` 现在的定位 = "连接卡片/RAG 的 tag 轴"（命名暂不改，见 ports.py 注释）。

## 2. 新增的 `execution.path`（codex 要认）
| path | 含义 | evidence_kind | execution.card | debug.drilldown | debug.retrieval |
|---|---|---|---|---|---|
| `card-grounding-then-sibling-card` | 原卡没答上 → **同 tag 兄弟卡答上了** | `source` | **兄弟卡**（不是原路由卡） | 兄弟卡的下钻 | `null` |
| `agentic-source-drilldown-then-sibling-card` | 同上（agentic 模式） | `source` | 兄弟卡 | 兄弟卡的下钻 | `null` |

已有的 `...-then-rag-fallback` 不变，但 `debug.retrieval` 现在多一个字段 **`boost_modules`**（list）：表示这次 RAG 是按这些 tag 加权的。`execution.steps` 在兄弟卡也miss时会多一条 `Sibling card <id> also returned NO_ANSWER`。

## 3. 关键坑：兄弟卡路径里 `execution.card` 是**兄弟卡**，不是用户问题路由到的那张卡
- `...-then-sibling-card` 的 `card_used` / `execution.card` = **被横跳到的兄弟卡**。
- 现有 `isRagFallbackResult` 判定（`endsWith("-then-rag-fallback")` 或 drilldown&&retrieval 同时非空）**不会**把兄弟卡路径判成回退态 → 它会被当成"普通单段 card-grounding"渲染，卡片显示成兄弟卡，**但丢了"从原卡跳过来"的故事**。

## 4. codex 要做的
1. **加 path 标签**（[app.js](frontend/app.js) `pathLabels`）：
   - `card-grounding-then-sibling-card` → 例如 "卡片下钻 → 同 tag 兄弟卡"
   - `agentic-source-drilldown-then-sibling-card` → "Agentic 下钻 → 同 tag 兄弟卡"
2. **兄弟卡路径也渲染成两段链路**（复用 handoff 30 的机制）：第一段=原卡下钻"已尝试/NO_ANSWER"，第二段=兄弟卡命中（标注"顺 tag 跳到 C-XXX"）。判定可加：`path.endsWith("-then-sibling-card")`。原卡 id 可从 `execution.steps` 里那条 `Hop to sibling card sharing tag: <id>` 解析，或后端如需可再加显式字段（要的话提需求）。
3. **RAG 回退面板显示 `boost_modules`**：在 retrieval 概要里加一行"tag 加权：人事服务"，让人看出这次 RAG 是按域加权过的。
4. 兄弟卡那段，沿用"命中卡片"卡片块即可，但建议补一句"这是顺 tag 跳到的邻居卡，非原始路由卡"。

## 5. 验收
- 选一个"原卡命中但答不上、同 tag 邻居卡能答"的问题：链路显示**原卡(已尝试) → 兄弟卡(命中)** 两段，最终答案 `card_used` = 兄弟卡。
- 一个"原卡和邻居都答不上"的问题：落 `...-then-rag-fallback`，retrieval 面板显示 `boost_modules`，steps 里有兄弟卡 miss 的那条。
- 原来能直接答的卡：单段，行为不变（无回归）。

## 6. 后端 token 说明（codex 不用管，仅同步）
兄弟卡选择是**确定性**的（无 LLM），只在"原卡已 NO_ANSWER"这条少数路径上最多多一次 answer 调用；tag 加权是纯本地打分，0 额外模型调用。
