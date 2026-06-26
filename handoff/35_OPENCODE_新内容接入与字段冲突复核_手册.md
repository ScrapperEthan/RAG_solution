# 35 OPENCODE/COPILOT 手册：新内容接入 + 字段冲突的大模型复核 + 人工冻结

**给 opencode / copilot（内网集成版）。claude 在外网定接缝 + 机制，opencode 在内网换真实数据/LLM 后跑通自检。** Ethan 手动把本文件拷进内网。

> 配套：接真实卡片看 [handoff/34](34_OPENCODE_接入真实cards_与mock自检_手册.md)；LLM 接入看 [handoff/27](27_OPENCODE_内网copilot集成到LLM_手册.md)。本手册只管 **新页进来怎么 ingest、字段冲突怎么被检出 / 大模型怎么复核 / 人工 approve 怎么冻结**。

## 0. 一句话
新的 Confluence / JSON 页进来 → ingest → reduce 检出「同字段多取值」冲突（暂取最新）→ **大模型复核给建议+风险** → approve 页**红色突出**冲突，人点一下冻结 → 决定写进账本，**全量重建后仍生效**。

## 1. 新内容怎么进来（ingestion）
三个 confluence provider（`config.yaml` 的 `providers.confluence`）：

| provider | 读什么 | 何时用 |
|---|---|---|
| `file` | `fixtures/confluence/*.md`（YAML front matter） | 现状 demo |
| `json` | `inbox/*.json`（`paths.incoming_dir`） | 内容以 JSON 形态来，只 ingest 这些 |
| `file+json` | md fixtures **＋** `inbox/*.json` | 新页**叠加**在已有内容上 → 才会和老值冲突 |

- JSON 页 = 一个 `RawPage` 对象，或一个对象数组。必填只有 `page_id` / `title` / `body_md`，其余有默认值（见 `backend/adapters/confluence_json.py`）。
- **`confluence_version` / `update_at` 要设得比被替代的页新**——冲突消解按「最新优先」，新值才会成为暂定值并触发复核。
- 跑：`python -m backend.pipeline demo --config config.incoming.yaml`（`config.incoming.yaml` 用的就是 `file+json`）。样例 `inbox/example_updated_portal_link.json` 改了 MDC portal link，会和 `C-0002 / Portal link / Link` 撞上。
- 真内网：把真实 JSON 丢进 `inbox/`，或走 `mcp` provider 拉真实 Confluence；流程一样。

## 2. 冲突怎么被检出（reduce，已有，本次结构化）
- `backend/reducer/service.py`：同一卡同一字段（同 normalized label）出现 **多个不同值** = 冲突。`resolve_subsection_fact_conflicts`（子条目事实）/ `merge_config_field`（config 字段）。
- **自动消解 = 最新优先**（`update_at` → `confluence_version`），其余丢弃，**绝不阻断构建**。卡片 `flags[]` 记一句；`review_queue.jsonl` 出一条 `fact-conflict` / `conflict`。
- 本次新增：这些 review 项**附带结构化** `conflict_id` + `candidates`（每个候选带 value/page_id/source_url/version/update_at）+ `auto_choice`。`conflict_id = CF-sha1(canonical|scope|label)`——**只认字段、不认值**，所以人工决定能跨重建存活；值集变了用指纹另判（见 §4 stale）。

## 3. 大模型复核 + 建议（新，`review-conflicts`）
- 新命令 `python -m backend.pipeline review-conflicts`（已并进 `demo`，在 reduce 之后、load 之前）。
- `backend/reducer/conflicts.py`：把 review_queue 的冲突转成结构化记录 → 对每条 open 冲突调 LLM（`task: card_review_conflict`）→ 应用决策账本 → 把已裁决的值**写回 cards_index.json** → 写 `outputs/conflicts.jsonl`。
- LLM 产出：`{recommended_value, reason_zh, reason_en, confidence, risk(low|medium|high)}`。离线 `MockLLM` 有确定性 stand-in（数字明显不同→high）。**内网换真实 LLM 不用改这里**——provider 走 `copilot` 即可（handoff/27），prompt/schema 已定。

## 4. 人工 approve：冲突红色突出 + 一键冻结（新）
- `frontend/approve.html` 顶部新增「**字段冲突复核**」面板：经后端打开本页（或带 `?api=`）时，从 `GET /api/conflicts` 拉取并渲染。
- 每条冲突一张**红色**卡：候选值并排（标「系统暂取最新」+ 页/版本/日期）、`风险 高/中/低` 徽章、大模型`建议采用`+理由+置信度。
- 按钮：「采纳建议并冻结」或某候选「选这个」→ `POST /api/conflicts/resolve {conflict_id, chosen_value, decided_by}` → 该卡变**绿色「已裁决」**，计数减一。
- 决定写进 **`outputs/conflict_decisions.jsonl`（账本）**。`clean_demo_outputs` 不删它；下次 `review-conflicts` 重新套用 → **重建后仍生效**。
- **stale**：账本里记了决策时的候选指纹；之后又来了新值（指纹变）→ 该冲突重新判为 `stale`、再次亮红并提示「有新值」，要求重新确认。

## 5. 接口（后端）
- `GET /api/conflicts` → `conflicts.jsonl` 数组；响应头 `X-Open-Conflicts`。
- `POST /api/conflicts/resolve` → 追加账本 + 重算状态 + 回写卡；未知 `conflict_id` → 404。
- `GET /api/health` 加 `conflict_count` / `open_conflict_count`。

## 6. 自检（逐项回报，脱敏）
- **A**. `python -m backend.pipeline demo --config config.incoming.yaml`；`outputs/conflicts.jsonl` 非空且每条 `llm_review` 有 `risk`。
- **B**. `curl -s localhost:8765/api/conflicts | python -m json.tool` 看到结构化冲突；`-D -` 看 `X-Open-Conflicts`。
- **C**. approve 页截图：红色冲突卡（带大模型建议）；点「采纳并冻结」后变绿；`conflict_decisions.jsonl` 多一行。
- **D**. 重建持久化：再跑一次 `reduce` + `review-conflicts`，已冻结的冲突仍是 `resolved`（账本生效）。
- **E**. 回归全绿：`python -m unittest discover -s backend/tests`（含 `test_conflicts` / `test_confluence_json` / `test_web.ConflictEndpointTest` / `test_approve_conflicts`）。

## 7. 范围 / 红线
- **检测/消解只在字段级**（同 label 不同值）。语义矛盾检测（10天 vs 两周、跨卡互斥）还没接——要做就在 `review-conflicts` 里加一遍 LLM 矛盾检查，产 `type=contradiction` 的记录走同一面板。
- **账本是真源、不可冒充人工**：`decided_by` 如实写（approve-ui / 具体人）。账本含真实裁决，**和 outputs 一样别传出内网**（已在 `.gitignore`）。
- 改 prompt / schema：动 `backend/reducer/conflicts.py` 的 `CONFLICT_REVIEW_*`（单一真源），同步 `MockLLM.mock_review_conflict` 和本手册；外网补测后同步回内网（理由同 handoff/27 §5）。
