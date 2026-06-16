# 33 `module` → `domains` 正式迁移（+ typed/命名空间）— opencode 内网迁移 + codex 前端改名

**claude 已在外网把数据字段 `module` 改名为 `domains`，并加 typed/命名空间能力。后端 + 测试 + 种子 fixture 全改完，116 tests OK。带向后兼容，所以拉下来不会立刻崩。** 日期：2026-06-17。

## 1. 改了什么
- 数据字段 **`module` → `domains`**，覆盖：全部 backend 代码、测试、两个种子 fixture（`fixtures/keyword_table.jsonl` = 审批词表；`fixtures/confluence/*.md` 的 front-matter）。
- 新增 **typed/命名空间**能力（`backend/domains.py`）：`domains` 每个条目可写成 `"namespace:value"`（如 `"system:Integration"`、`"phase:Onboarding"`）；**裸值 = 默认命名空间 `domain`**。匹配语义（`domain_matches`）：
  - **裸查询按 value 跨命名空间匹配**（`"Integration"` 命中 `"Integration"` 和 `"system:Integration"`）；
  - **带命名空间的查询要求 ns + value 都相等**。
  - 建议命名空间（约定，不强制，在词表里 curate）：`domain`（业务域，默认）/ `system`（功能组件/标准）/ `phase`（流程阶段）。
- 检索过滤、tag 加权 boost、兄弟卡 tag 匹配**全部走 `domain_matches`**（命名空间感知；现有裸值零行为变化）。

## 2. 向后兼容（所以现在不会崩）
- **词表加载** `normalize_concept` 和 **页面 meta** `confluence_file` 都**同时接受旧 `module` 键**（`raw.get("domains") or raw.get("module")`）。
- **Web API 兼容旧前端**（前端还没改时也能跑）：
  - `ChatRequest` 仍接受 `module` 入参（`request.domains or request.module`）；
  - `/api/golden` 同时返回 `domains` 和 `modules`；
  - `public_ref` / `/api/cards` 每条同时带 `domains` 和 `module`；
  - agentic debug 的 `retrieval` 同时带 `boost_domains` 和 `boost_modules`。

## 3. opencode（内网）要做的
1. `git pull`。
2. **迁移你那份真实数据**（外网只改了合成 demo 的）：把内网**审批词表**和**页面 front-matter** 里的 `module` 列/键改名 `domains`。短期可不改（兼容读会兜底），但**建议改**，否则导出的词表快照表头会不一致。
3. **重跑流水线**（`ingest→…→load`，或 `pipeline demo` 的内网等价），让所有 outputs 用新的 `domains` 重生。
4. 复测：检索 + 卡片 + module/domains 过滤（CLI `--filter domains=...`）正常。

## 4. codex（前端）执行清单 —— 前端改名 `module` → `domains`
后端**已对旧前端全兼容**（§2），所以你可以**增量改、随时跑、app 全程不崩**。这是完整的独立任务，照下面做即可。

**4.1 footprint（迁移时 `module` 出现次数，改完应≈0，`labels` 不算）**

| 文件 | 次数 | 主要形态 |
|---|---:|---|
| `cards.html` | 35 | 知识图谱：`moduleEdge*` / `includeModuleEdges` / `moduleKey` / `is-module` 边 / `module-group`/`module-title` / `card.module` 读取 / 文案 |
| `approve.html` | 16 | 词表审批页：字段名展示 + `module` 列 |
| `app.js` | 14 | `moduleSelect` / `renderModules` / `request` 体 `module:` / `ref.module`/`card.module` 读取 / `module-tags` |
| `flow.html` | 13 | 流程讲解页文案 + schema 示例里的 `"module"` |
| `offline-demo.js` | 5 | 离线 mock 数据的 `module: [...]` / `modules: [...]` 键 |
| `style.css` | 2 | `.module-tags` / `.module-edge-toggle` 等类名 |
| `debug-panel.js` | 2 | `retrieval.boost_modules` 读取 |
| `index.html` | 1 | `<select id="moduleSelect">` |

**4.2 改名规则（标识符 → 数据键 → 文案）**
- 标识符/CSS：`moduleSelect`→`domainSelect`、`renderModules`→`renderDomains`、`moduleEdgeToggle`/`moduleEdgeField`→`domainEdge*`、`includeModuleEdges`→`includeDomainEdges`、`moduleKey`→`domainKey`、`.module-tags`/`.module-edge*`/`.module-group`/`.module-title`/`.is-module`→`domain-*`（CSS 同步）。
- 读后端数据：`card.module`/`ref.module`→`.domains`、`payload.modules`→`payload.domains`、`retrieval.boost_modules`→`boost_domains`、知识图谱边标签 `"module"`→`"domains"`。
- 发请求体：`{ module: ... }`→`{ domains: ... }`。
- 离线 mock（offline-demo.js）：把数据里的 `module:`/`modules:` 键改 `domains:`。
- 展示文案："module / 域标签 / 模块" 统一成 "domains / 域"。
- **不要动 `labels`**（Confluence 原生标签，和 domains 是两回事）。

**4.3 同步改这两份测试断言**（claude 特意没动它们，保持与现有前端一致）：`backend/tests/test_cards_knowledge_map.py`、`backend/tests/test_frontend_clarity.py`——里面断言的是前端字符串（如 `mode:"module"`、`moduleKey`、`boost_modules`），改前端时一起改成 `domains` 版。

**4.4 验收**
- 浏览器：module 下拉能选并过滤、卡片/refs 上的域标签显示、cards.html 知识图谱的同域边渲染、debug 面板 "tag 加权" 显示 `boost_domains`。
- 前端文件里 `module` 残留≈0（`labels` 除外）。
- `grep -r module backend/tests/test_cards_knowledge_map.py backend/tests/test_frontend_clarity.py` 应只剩你已同步成 `domains` 的内容。
- 全套 backend 测试仍绿。
- **改完后**通知，claude 删掉 §2 的后端兼容别名（清单见 §5）。

## 5. 前端迁移完成后要删的后端兼容别名
- `web.py`：`public_ref` 的 `"module"`、`/golden` 的 `"modules"`、`/cards` 的逐卡 `module`、`ChatRequest.module`（+ `resolve_chat` 的 `or request.module`）。
- `agentic/service.py` `_debug_retrieval` 的 `"boost_modules"`。
- （词表/页面 meta 的 `or raw.get("module")` 兜底可保留更久，等内网数据确认全迁完再删。）

## 6. 验收
- `pipeline demo` 重跑后，cards/refs/inverted_index 里是 `domains` 字段。
- `--filter domains=Q2 - Engagement` 能过滤；`--filter domains=system:Xxx` 形态也被接受（命名空间感知）。
- 旧前端（未改）仍能显示 tag、跑 module 过滤（靠兼容别名）；codex 改完后用 `domains` 同样工作。
- 全套 backend 测试绿（外网 116 OK）。
