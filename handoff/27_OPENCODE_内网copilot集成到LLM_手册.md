# 27 OPENCODE 手册：把内网 copilot 接到 LLM port

**给 opencode（内网集成版）。claude 在外网定接缝+验收标准，opencode 在内网填传输层+调试，遇外网能改的部分写问题回报、claude 来改。** Ethan 手动把本文件拷进内网。

## 0. 一句话任务
本系统所有 LLM 调用都走一个 port（`backend/ports.py` 的 `LLM.complete_json` / `complete_text`）。你**只需实现一个内网 copilot 适配器的传输层**，让真实 copilot 顶替 `MockLLM`。**除此之外什么都不要改。**

## 1. claude 已在外网预埋好的接缝（直接用，别重写）
已 commit 到外网仓库、且全测通过（93 tests OK）：

- **`backend/adapters/llm_copilot.py`** — `CopilotLLM` 适配器骨架：
  - `complete_json` / `complete_text` 已按 port 写好；
  - `_extract_json()` 已实现并测过（容忍 ```json fence、前后散文、内嵌单对象、字符串内的花括号）——**复用它，不要重写**；
  - **唯一的空缺是 `_call_copilot()`**，现在 `raise NotImplementedError`，就是留给你的。
- **`backend/factory.py`** — 已加分支 `if provider == "copilot": return CopilotLLM(config["llm"])`。
- **`backend/tests/test_llm_copilot_adapter.py`** — `_extract_json`/工厂接线/接缝惰性 的回归测试。
- 配置开关：`config.yaml` 里把
  ```yaml
  providers:
    llm: copilot        # 原来是 mock
  llm:                  # 新增块，字段由你的 copilot 决定
    base_url: "https://<内网 copilot 端点>"
    model: "<模型名>"
    api_key_env: "<读密钥的环境变量名>"   # 密钥走 env，不要写进文件
  ```

## 2. 你要做的唯一一件事：实现 `_call_copilot`
在 `backend/adapters/llm_copilot.py` 的 `_call_copilot(system, user, *, temperature, max_tokens, want_json) -> str` 里，写内网 copilot 的**真实传输**：端点、鉴权（token/cookie/SSO/内网网关）、请求体、从响应里取出 message 文本。契约：
- 返回 copilot 的**文本内容 str**即可（JSON 调用时哪怕带 fence/散文也行，外层 `_extract_json` 会兜底，你**不用**在这里解析 JSON）；
- `want_json=True` 时，若 copilot 有严格 JSON 模式（如 `response_format=json_object`）就开它，没有也行；
- `temperature` 透传（copilot 不支持就在代码注释里写明）；
- 传输/鉴权/HTTP 失败要**抛清晰异常**，不要 `return ""`。

**封装硬规则：copilot 专有的端点/鉴权/SDK 代码只能出现在这个文件里。** 别往 services/prompts/factory 里漏。

参考模板：`backend/adapters/llm_openai_compat.py`（`OpenAICompatLLM`）就是同形状的真实 HTTP 适配器，照着改传输层最快。

## 3. copilot 必须能产出的 JSON 契约（11 个调用点）
每个 LLM 调用的 `system` 提示带一个 `task:` 标签，调用方按各自 schema 校验返回。copilot 对这些都要能回**合法 JSON 对象**（`_extract_json` 兜底解析）：

| `system` task 标签 | 期望返回（对象） | 调用方 |
|---|---|---|
| `card_map_section` | section 抽取记录 | mapper |
| `card_map_page_summary` | 页摘要 | mapper |
| `card_reduce_normalize_section` | `{"canonical_ids":[...], "needs_review":[...]}` | reducer normalize |
| `card_reduce_resolve_aliases` | `{"aliases":[...]}` | reducer |
| `card_expand_boundary` | `{"boundary": "..."}` | reducer/boundary |
| `card_summarize` | `{"summary_zh":"...","summary_en":"..."}` | reducer 卡片摘要 |
| `card_discover_topics` | 发现的 topic 列表对象 | discover |
| `answer_from_context` | `{"answer":"..."}`（无依据以 `NO_ANSWER` 开头） | answer |
| `agentic_route_card` | `{"canonical_ids":[...]}` | agentic 选卡 |
| `agentic_classify_intent` | `{"intent":"exact"\|"concept"}` | agentic 意图 |
| `judge_faithfulness` | `{"score": 0.0~1.0}` | eval |

> 各 schema/必需键以外网代码为准（`backend/answer/service.py`、`backend/agentic/service.py`、`backend/reducer/service.py`、`backend/schemas/validation.py`）。**别去改这些 prompt/schema**——见 §5。

## 4. 验收标准（claude 制定，opencode 调试达标后逐项回报）
- **A. 不破 mock 回归**：`providers.llm: mock` 下 `python -m unittest discover -s backend/tests` 仍 **93 OK**（证明你只动了 `_call_copilot`，没碰共享逻辑）。
- **B. 端到端跑通**：`providers.llm: copilot` 下，对内网真实 Confluence 切片跑 `ingest → map → reduce → load → answer`（`python -m backend.pipeline <cmd>`），**11 个调用点全部返回满足 schema 的对象、无 JSON 解析失败**。贴每步的 stdout（脱敏）。
- **C. JSON 健壮性**：copilot 即便包 ```fence / 加前后散文也能解析（复用 `_extract_json`）；彻底无法解析时抛 `CopilotResponseError`，**不静默返回 `{}`**。
- **D. `complete_text`** 返回纯字符串（找一个走 text 的路径验证，或单测）。
- **E. 密钥安全**：鉴权走 config/env，仓库里**无明文 secret**，`git diff` 不含密钥。
- **F. 封装审计**：`grep` 显示 copilot 端点/鉴权/SDK 标识**只出现在 `llm_copilot.py`(+config)**，别处为 0。
- **G. temperature**：`0.0` 透传；copilot 忽略则代码注释写明。

## 5. 遇到"外网能改的部分"——不要改，写问题回报
如果你发现**必须改 prompt / service / schema / 检索 / 前端**才能让 copilot 跑通（例：某调用点 copilot 总产坏 JSON、某 schema 太严、某 prompt 对内网模型水土不服），**禁止在内网直接改**。改为：

1. 写 `handoff/28_OPENCODE_问题回报_<简述>.md`，写清：**哪个调用点 / copilot 实际返回了什么（脱敏样例）/ 现有外网代码为什么失败 / 你建议怎么改**。
2. Ethan 把它带到外网 → **claude 在外网改 + 补测试**（保持 MockLLM 可测）→ Ethan 同步回内网。
3. 你**只**把你的 `_call_copilot` 适配器接上复用，复跑验收 A–G。

> 为什么这么严：外网仓库是**共享逻辑的唯一真源**、且必须永远能用 MockLLM 离线测试。内网私改共享逻辑会让内外网悄悄分叉，破坏同步纪律。**封装边界 = `_call_copilot` 之内归你，之外归外网。**

## 6. 回报物
- `llm_copilot.py` 的 `_call_copilot` 实现 diff；
- 验收 A–G 逐项结果（B 贴端到端日志、F 贴 grep 结果，均脱敏）；
- 若有，§5 的问题回报 `.md`。

## 7. 范围外（本手册不管）
- **embedder**：内网向量化是另一条线，factory 已有 `embedder: intranet` 槽（`IntranetEmbedder`），同样的适配器封装法，但**不在本手册范围**，需要时另开一份。
- **store**：`json`/`chroma`/`pgvector` 已就绪，按 config 选，不用动代码。
