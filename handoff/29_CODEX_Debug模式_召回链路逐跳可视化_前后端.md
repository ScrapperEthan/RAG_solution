# 29 CODEX 规格：Debug 模式 — 召回链路逐跳可视化（前后端）

**给 codex（外网仓库 `backend/` + `frontend/`）。claude 写规格，codex 实现，claude review。**

> 目标：把"问题 → 命中卡 → 取证下钻 → 喂给 LLM 的原文 → 答案"这条**召回链路**在前端摊开，每一跳能看到真实 JSON 字段（refs / contexts / subsections / anchor / section_id / score …），方便定位"为什么这条答不出来 / 取到的是什么"。**纯增量、debug 开关控制，绝不改变非 debug 的回答行为。**

## 0. 先讲清楚链路有哪几跳（实现前先对齐）
回答入口在 `backend/agentic/service.py::AgenticService.answer()`，按 `answer_mode` 分流。两条主链：

**A. pure-rag（不碰卡片）**
1. `query`
2. `Retriever.retrieve()` → 在向量库（refs/descriptions/summaries）检索 → 得到 **refs**（每条带 `section_id / title / heading_path / source_url / score / body_md`）
3. `AnswerService.answer_from_refs(query, refs)` → LLM 读 `body_md`（= **contexts**）→ 答案

**B. 卡片路径（agentic / card-grounding / card-direct）**
1. `query` →（agentic）`classify_intent` → `intent`
2. `find_card()` → `route_card_llm`(LLM 读卡目录选 id) 或 `match_card_keyword`(关键词兜底) → 命中 **card**
3. 取证：`refs_for_card(card)` → 从卡片的 `subsections[].facts[].source_section_ids` / `subsections[].source_section_ids` / `fields[].source_section_ids` **收集 section_id** → 在 `loaded_refs` 里查 → 得到 **refs**
   （`card-direct` 不走取证，直接 `answer_from_card` 拼 `fields` 的值）
4. `answer_from_refs` → 答案

**用户最想看的就是 B-3 这一跳**：收集了哪些 section_id、哪些在 `loaded_refs` 里命中、哪些没命中（没命中 = 取证失败的根因，例如上轮的格式 bug）。

## 1. 现状（复用，别重写）
- `backend/web.py`：`ChatRequest(query, golden_id, language, module, answer_mode)` → `runtime.answer(query, filters, answer_mode)` → `AgenticService.answer(query, variant, filters)`；`@app.post("/api/chat/stream")` 用 ndjson 流式返回，末行 `{"type":"result","result":{...}}`。
- 回答 `result` **已经带**这些字段（debug 先把它们摊开就够看一大半）：
  - `answer` / `citations` / `retrieved_section_ids` / `contexts`（= 喂给 LLM 的 body_md 列表）/ `drilled` / `diagnostic`
  - `evidence_sections`（= 实际用到的 refs 数组，含 section_id/heading_path/source_url/score/body_md）
  - `card_evidence`（card-direct 用到的字段）
  - `execution`（`requested_mode/path/evidence_kind/steps/intent/drilled/diagnostic/card/family`）
- 前端 `index.html`/`app.js` 渲染答案 + 执行轨迹；`cards.html` 渲染卡片树 + drill 高亮。**沿用 `style.css`，纯 vanilla，无打包工具。**

## 2. 后端改动（debug 开关 + 补齐缺失的跳）

### 2.1 开关穿透
- `ChatRequest` 增加 `debug: bool = False`。
- `runtime.answer(query, filters, answer_mode, debug=False)` → `AgenticService.answer(query, variant, filters=filters, debug=False)`。
- **debug 默认 False；非 debug 路径的返回结构与回答内容必须一字不变。**

### 2.2 当 `debug=True` 时，给 `result` 加一个 `debug` 对象
现有 `result` 字段已能摊开大半，但有几跳的内部状态现在**丢失了**，必须补：路由怎么选的、取证收集 vs 命中 vs **未命中** 的 section_id。结构：

```jsonc
"debug": {
  "query": "...",
  "answer_mode": "agentic",
  "intent": "exact",                         // 或 null
  "routing": {
    "method": "llm-router" | "keyword-fallback" | "none",
    "llm_returned_ids": ["C-0002"],          // route_card_llm 实际返回（无则 []）
    "catalog_size": 7,                        // 候选卡目录大小
    "chosen_card": "C-0002"                   // 命中卡 id（无则 null）
  },
  "retrieval": {                              // pure-rag / fallback 才有；否则 null
    "index": "both", "search": "hybrid", "top_k": 8,
    "hits": [ {"section_id":"...","title":"...","heading_path":["..."],"score":0.83} ]
  },
  "drilldown": {                              // 卡片取证才有；否则 null
    "gathered": [ {"section_id":"9100001#... > PN > Delivery Mode","origin":"fact"} ],   // 收集到的（按 specific→field 顺序）
    "resolved_section_ids": ["9100001#... > PN > Delivery Mode"],   // 在 loaded_refs 命中的
    "missed_section_ids": [ ],                // 收集了但 loaded_refs 里没有 —— 取证失败就看这里
    "counts": {"gathered": 16, "resolved": 8, "missed": 0, "capped_to": 8}
  },
  "refs_used": [                              // 真正喂给 answer_from_refs 的 refs（= contexts 的来源）
    {"section_id":"...","anchor":"...","heading_path":["..."],"source_url":"...","score":0.0,"body_md":"...(原文)"}
  ],
  "card_used": {                             // 命中卡的结构（debug 取证用）；无卡则 null
    "canonical_id":"C-0002","canonical_name":"...",
    "subsections":[ {"name":"...","source_section_ids":["..."],
                     "facts":[ {"label":"...","value":"...","source_section_ids":["..."]} ]} ],
    "fields":[ {"field":"definition","tier":"narrative","source_section_ids":["..."]} ]
  }
}
```

### 2.3 实现要点（最小、单一真源）
- **取证收集逻辑抽成一个函数**，例如 `_card_section_ids(card) -> List[Tuple[origin, section_id]]`（保持现有"子项 facts → 子项 → field"的顺序）。`refs_for_card` 复用它（行为不变）；debug 的 `drilldown.gathered/resolved/missed` 也用它：`missed = [sid for _,sid in gathered if sid not in self.refs]`。**这样去重/顺序/截断只有一处定义。**
- **路由方法**：让 `find_card` 能告知它是走 `llm-router` 还是 `keyword-fallback`（小重构：返回 `(card, routing_meta)` 或写入传入的 debug dict）。**不改命中结果**，只记录。
- `refs_used` 直接用现有 `evidence_sections`（同一份 refs）；`body_md` 给全文（前端自己截断显示）。
- debug 对象**只在 `debug=True` 时构造**，不污染正常响应、不进 eval。

## 3. 前端改动（Debug 面板）

### 3.1 开关
- `index.html`：控制面板加一个 **「Debug 模式」** 勾选框。勾上后提交时带 `debug:true`，并在「回答与执行轨迹」下方展开 **Debug 链路面板**。
- `cards.html`：提问区同样加 Debug 勾选（它已会渲染 drill 路径，Debug 面板作为补充）。

### 3.2 逐跳渲染（hop-by-hop）
按链路顺序渲染卡片式步骤，每跳：标题 + 关键字段摘要 + **「查看原始 JSON」可展开**（`<details>` + `<pre>` 显示该跳的 JSON 子对象）：
1. **Query / Intent** — `debug.query`、`debug.intent`、`answer_mode`
2. **路由 Routing** — `method`、`llm_returned_ids`、`chosen_card`、`catalog_size`
3. **检索 / 取证** —
   - pure-rag：渲染 `retrieval.hits` 表（section_id / heading_path / **score**）
   - 卡片：渲染 `drilldown`，**`missed_section_ids` 用红色高亮**并标注"收集到但 loaded_refs 未命中（取证会失败）"；显示 `counts`
4. **喂给 LLM 的原文 refs_used** — 每条一块：`section_id`、`anchor`、`heading_path`、`source_url`(可点)、`score`、**`body_md` 全文（可滚动框）**；每条带「查看原始 JSON」
5. **卡片结构 card_used** — subsections / facts / fields 的 `source_section_ids`（和第 4 跳对照，看"卡片指向的段落"是否真被取到）
6. **答案** — `answer`、`citations`、`diagnostic`（有则红字）、`execution.steps`

### 3.3 兜底
- `debug` 不存在（后端旧版/未勾选）时，Debug 面板用**现有** `evidence_sections`/`card_evidence`/`execution` 也能摊出第 4/6 跳，并提示"后端未返回 debug，部分跳不可见，请勾选 Debug 重新提问"。
- 离线/无后端：用现有脱敏 sample 也要能渲染 Debug 面板（不报错），**不准硬编码任何真实内网数据**。

## 4. 验收清单
- [ ] `debug=False`（默认）时，`result` 结构与回答**逐字不变**（加回归断言：不含 `debug` 键）。
- [ ] `debug=True` 时 `result.debug` 含 §2.2 全部跳；`drilldown.missed_section_ids` 在"收集了但未命中"时非空、否则为空。
- [ ] 前端 Debug 面板逐跳显示，每跳可展开原始 JSON；`refs_used[].body_md` 全文可见；`missed_section_ids` 红色高亮。
- [ ] pure-rag 显示 `retrieval.hits`+score；卡片路径显示 `drilldown`+`card_used`；两者切换正确。
- [ ] 关掉 Debug 后回到原样；无后端时 sample 也能渲染面板。
- [ ] 纯 vanilla、无新依赖、复用 `style.css`；无硬编码内网数据。

## 5. 硬规则
- **debug 必须 opt-in、零副作用**：不改命中卡/检索/取证的任何结果，只"旁路记录"。`_card_section_ids` 是取证 section_id 的**唯一真源**，`refs_for_card` 与 debug 都复用它。
- 不动上一轮 `aa70984` 的修复语义（section_id 用完整路径、不从 anchor 反推）。
- 回报：前后端 diff + Debug 面板截图（脱敏 sample / Golden，**不要贴真实内网数据**）+ `debug=False` 不变的回归测试。
