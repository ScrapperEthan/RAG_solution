# 21 CODEX 前端规格：卡片可视化 + 回答 drill 路径

**给 codex（外网仓库 `frontend/`）。claude 写规格，codex 实现，claude review。**

## 0. 两个目标（一个交付物同时满足）

1. **人看/审/改卡**：把 `outputs/cards/*.json` 的 `topic → subsections → facts/fields` 层级可视化，方便理解、阅读、定位、对照源链接。
2. **可视化 LLM 回答的 drill 路径**：用户提问 → 命中某 topic（card）→ 落到某 subsection/field → 取到某条 fact → 给出带 citation 的答案。要把这条"找 topic→找子项→找事实"的链路在卡片结构上**高亮走一遍**。

## 1. 现状（别重写，复用）

- 前端是**纯静态 + FastAPI 挂载**（`backend/web.py` 把 `frontend/` 挂在 `/`）。已有 `index.html`(chat demo)、`app.js`、`style.css`、`approve.html`(审词表)、`flow.html`。**沿用 `style.css` 的 CSS 变量与 vanilla JS 风格，不要引入框架/打包工具。**
- 回答链路已经有了，**直接消费**：`POST /api/chat/stream`（NDJSON 流），每行一个对象，最后一行 `{"type":"result","result": <见 §3.2>}`。
- **缺的就是卡片视图本身**，以及把 `result.execution` 渲染成路径。

## 2. 交付物

- 新增单文件 **`frontend/cards.html`**（参照 `approve.html` 的自包含风格：可内联 JS/CSS，复用 `style.css`）。
- 从 `index.html` 顶部导航加一个链接到 `cards.html`（最小改动，别动 `app.js` 逻辑）。
- 内置一个**脱敏 sample**（§3.3）作为离线 dev fixture；真实数据一律从 `outputs/` 动态读，**不准硬编码任何内网数据/URL/人名**。

## 3. 数据契约

### 3.1 卡片 schema（来自 `outputs/cards_index.json` = card 数组；单卡同结构）

```jsonc
{
  "canonical_id": "C-1005",
  "canonical_name": "Application Engagement Contacts and Ticket Endpoints",
  "topic_class": "reference",
  "aliases": ["contact point", "ticket end point"],
  "module": ["02 - Engagement", "MDC Onboarding"],
  "boundary": "不同应用和治理流程的工单入口、联系人和接洽方式。",
  "topic_type": "reference",
  "status": "approved",
  "keywords_raw_agg": ["..."],            // 扁平证据词（可折叠展示）
  "concepts_agg": ["..."],
  "questions_agg_en": ["..."],
  "questions_agg_zh": ["..."],
  "source_section_ids": ["3725660167#... > MDC > Contact Point"],
  "subsections": [                         // 主层级：topic → subsection → facts
    {
      "name": "MDC",
      "summary": "MDC: Contact Point: ...",
      "key_points": ["Contact Point: ..."],
      "facts": [
        {
          "label": "Contact Point",
          "tier": "inline-value",          // inline-value | narrative | pointer-only
          "value": "Joe Z Y JIAN",
          "pointer_to": null,
          "sources": [{"page_id":"...","anchor":"...","source_url":"https://...","confluence_version":31}],
          "source_section_ids": ["..."]
        }
      ],
      "evidence_keywords": ["..."],
      "source_section_ids": ["..."],
      "sources": [{"page_id":"...","anchor":"...","source_url":"https://...","confluence_version":31}]
    }
  ],
  "fields": [                              // 卡级字段：definition/overview/config/troubleshoot/pointer/related_components
    {"field":"definition","tier":"narrative","value":"...","sources":[{...}],"evidence_keywords":["..."],"source_section_ids":["..."]}
  ],
  "flags": []                              // 例如冲突提示
}
```

注意：`subsections[].facts` 可能为空（`facts: []`）——要**优雅显示**"无抽取事实"，不要报错或留白。`fields[].value` 对 `pointer-only` 为 null、要显示 `pointer_to`。

### 3.2 回答结果 schema（`/api/chat/stream` 最后一行 `result`）

```jsonc
{
  "query": "What is the contact point for MDC?",
  "answer": "Joe Z Y JIAN",
  "citations": ["https://.../viewpage.action?pageId=3725660167"],
  "retrieved_section_ids": ["3725660167#... > MDC > Contact Point"],
  "drilled": false,
  "card_evidence": [ {"field":"...","tier":"inline-value","value":"...","pointer_to":null,"sources":[{...}]} ],
  "evidence_sections": [ {"section_id":"...","title":"...","heading_path":["...","MDC","Contact Point"],"source_url":"https://...","module":[],"score":0.83,"body_md":"..."} ],
  "execution": {
    "requested_mode": "agentic",
    "path": "agentic-card-direct",         // 见 backend/agentic/service.py 的各分支
    "evidence_kind": "card",               // card | source | retrieval | none
    "steps": ["Match approved canonical card","Classify intent as exact","Use answerable card fields directly"],
    "intent": "exact",                     // exact | concept | null
    "drilled": false,
    "card": {"canonical_id":"C-1005","canonical_name":"...","module":["..."]}  // 可能为 null（RAG fallback）
  }
}
```

**请求体**：`POST /api/chat/stream`，body `{"query": "...", "answer_mode": "agentic", "language": "en", "module": null}`。`answer_mode` 可选：`agentic|pure-rag|card-direct|card-grounding|llm-direct`（默认 `agentic`）。响应是 `application/x-ndjson`：逐行 `{"type":"meta"|"token"|"result"|"error", ...}`；`token` 是答案流式片段，`result` 是上面这坨。

### 3.3 离线 sample（codex 内置，无内网数据）

放一份脱敏的 `SAMPLE_CARD` 和 `SAMPLE_RESULT`（结构同上、用 `example.test` 域名、假名 "A B CHEN"），让 `cards.html` 在**没有后端/没有 outputs 时**也能渲染 demo，并能离线渲染一条 drill 路径。

## 4. 功能规格

### A. 卡片浏览
- 左栏：卡片列表，按 `module` 分组；显示 `canonical_name`、`topic_class`、status；顶部一个搜索框（匹配 name/aliases/keywords）。
- 右栏：选中卡详情，**层级树**：
  - 顶：`canonical_name` + `boundary` + `aliases` + `module` + `flags`。
  - **Subsections**（主体）：每个 subsection 一块，标题 `name`，下面 `facts` 列表，每条 fact 显示 `label`、`value`（或 `pointer_to`）、**tier 徽标配色**（inline-value=绿/narrative=灰/pointer-only=蓝）、`sources` 渲染成可点的 Confluence 链接（新标签页打开）。`facts: []` 显示淡色"（无抽取事实）"。
  - **Fields**：definition/overview/config/troubleshoot/related_components 等，同样 tier 配色 + sources。
  - 可折叠/展开；`keywords_raw_agg`/`questions_agg` 默认折叠。
  - 每个 `section_id`/`anchor` 提供"复制"。

### B. 回答 drill 路径（核心）
- 顶部一个提问框 + answer_mode 下拉；提交后 `POST /api/chat/stream`，流式把 `token` 拼成答案。
- 拿到 `result` 后，**在卡片树上把路径走一遍**（高亮 + 顺序编号）：
  1. **用户问题** → 显示 query 与 `execution.intent`。
  2. **命中 topic** → 用 `execution.card.canonical_id` 在左栏定位并高亮该卡，右栏自动展开它。
  3. **逐步** → 把 `execution.steps[]` 渲染成有序步骤条（"匹配卡 → 判定 intent → 取字段/钻源"）。
  4. **落到事实** → 用 `card_evidence[]`（card 模式）或 `evidence_sections[]`（source/retrieval 模式）高亮对应的 fact/field/section；把它们与右栏树里的条目对应高亮（按 `source_section_ids`/`anchor` 匹配）。
  5. **答案 + citations** → 显示最终 `answer` 和 `citations`（可点）。
- 离线模式：提供"贴一段 result JSON"输入框，直接渲染步骤 4 的高亮（不依赖后端）。

### C. 交互细节
- tier 图例；空态/错误态（API 不可用时回退到 sample + 提示）；移动端单列堆叠基本可用。
- 不破坏 `index.html`/`app.js` 现有功能；只加一个导航链接。

## 5. 验收清单
- [ ] `cards.html` 能从 `cards_index.json` 渲染全部卡，subsection/fact/field 层级正确，tier 配色正确，source 链接可点。
- [ ] `facts: []` / 空 subsection / pointer-only 字段都优雅显示，不报错。
- [ ] 提问走 `/api/chat/stream`，答案流式出现，`execution.steps` 渲染成路径，命中卡被高亮、cited fact/section 被高亮。
- [ ] 断网/无后端时，内置 sample 能渲染卡 + 用 `SAMPLE_RESULT` 渲染一条离线 drill 路径。
- [ ] 纯静态、无新依赖/无打包工具，复用 `style.css`；无任何硬编码内网数据。

## 6. 硬规则（同 opencode 风格）
- **以前端为主**，不改 backend 业务逻辑。若发现确实需要后端补字段（见 §7），**不要自己改 backend**，在 `handoff/22_CODEX_xxx.md` 写清楚需要什么字段、为什么，由 claude 来加。
- 回报时给：`cards.html` 的实现 + 截图/录屏（用脱敏 sample，不要贴真实内网数据）。

## 7. Phase 2（后端，claude 负责，先不依赖）
当前 `execution` 只标到 **card + field/section** 粒度，没到 **subsection/fact** 粒度。Phase 1 先用现有数据把路径走到 card+field/section 就够看。等 Phase 1 通过后，如果要"高亮到具体哪个 subsection 的哪条 fact"，claude 会在 `backend/agentic/service.py` 给回答结果加一份 **provenance**（每条 cited section → `{canonical_id, subsection_name, fact_label}`），前端再据此精确高亮。**codex 不用管这块。**
