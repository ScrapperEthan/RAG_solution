# Confluence RAG / Card PoC

这份仓库现在包含一套**内网外可运行**的 PoC 骨架。启动方式统一走 `uv sync` / `uv run`。核心业务代码面向 4 个端口编程:

- `ConfluenceSource`: 本地用 `FileConfluenceSource` 读 `fixtures/confluence/*.md`; 内网由 opencode 填 `McpConfluenceSource`。
- `LLM`: 本地用 `MockLLM` 走同一套 `complete_json` 端口; 内网由 opencode 接 Copilot / gpt-5.5 适配器。
- `Embedder`: 本地用 deterministic hash embedding 保证无需下载模型即可跑; 内网可换 BGE-m3/内部 embedding。
- `VectorStore`: 本地用 `JsonVectorStore`; 内网可切到 pgvector adapter/DSN。
- 可选快速向量库: `ChromaVectorStore`,配置见 `config.chroma.yaml`。

## 安装依赖

```powershell
uv sync
```

## 本地一键跑通

```powershell
uv run python -m backend.pipeline demo
```

这会生成:

- `outputs/capture/*.json`
- `outputs/map/map_*.json`
- `outputs/cards/*.json`
- `outputs/inverted_index.jsonl`
- `outputs/review_queue.jsonl`
- `outputs/eval_report.json`
- `outputs/eval_report.md`

查看状态:

```powershell
uv run python -m backend.pipeline status
```

分步运行:

```powershell
uv run python -m backend.pipeline ingest
uv run python -m backend.pipeline map
uv run python -m backend.pipeline reduce
uv run python -m backend.pipeline load
uv run python -m backend.pipeline retrieve --query "DM plugin default batch_size?"
uv run python -m backend.pipeline answer --query "DM plugin default batch_size?"
uv run python -m backend.pipeline eval
```

使用 Chroma 快速验证:

```powershell
uv run python -m backend.pipeline demo --config config.chroma.yaml
uv run python -m backend.pipeline retrieve --config config.chroma.yaml --query "DM plugin default batch_size?"
```

## 打开看板

先跑 demo，然后从项目根目录启动静态服务器:

```powershell
uv run python -m http.server 8765
```

打开:

```text
http://localhost:8765/frontend/
```

看板只读取 `outputs/eval_report.json`，不依赖内网。

## 跑测试

```powershell
uv run python -m unittest discover -s backend/tests
```

## 进内网后交给 opencode 的工作

只替换端口实现和配置，不改业务逻辑:

1. `backend/adapters/confluence_mcp.py`: 接真 Confluence MCP。
2. `backend/adapters/llm_gpt55.py`: 指向内网 gpt-5.5；若 OpenAI-compatible，配置即可。
3. `backend/adapters/embedder_intranet.py`: 需要时接内网 embedding；维度必须和 store 一致。
4. `backend/adapters/store_pgvector.py`: 接内网 pgvector，或把 `config.yaml` 的 store DSN 指向已有实现。

内网配置示例见 `handoff/02_OPENCODE_内网补充.md`。
RAGAS/Chroma 说明见 `handoff/03_OPENCODE_RAGAS_CHROMA.md`。

## 当前实现边界

- 本地 demo 使用 mock Confluence + deterministic `MockLLM` + hash embedding，目标是把端口、schema、产物、eval 和看板跑通，不代表真实业务效果。
- `map/reduce/answer/agentic` 已通过 `LLM.complete_json` 端口接入；外网不实现真实 Copilot 调用，内网只需要补 adapter 和配置。
- chunking 已支持 H2/H3、代码围栏保护、可选小段合并、大段按 Markdown block 二次切分、overlap。当前 `min_merge_tokens: 0` 是为了保持 fixture golden 的 section id 稳定；真实切片可调高后重新生成 golden。
- schema 校验覆盖 map/card/inverted_index/review_queue/eval_report 的关键字段、enum、类型和 tier 约束。
- `fixtures/golden_seed` 当前是 15 题起步回归集。不要在 mock Confluence 上硬扩成“正式 50 题 golden”；真实 golden 应进内网后从真实 holdout 原文生成、人工抽检并冻结。
- `PgVectorStore` 目前是签名完整的 adapter skeleton；当前环境和内网启动流程都不依赖 Docker。
- `ragas` 和 `chromadb` 已写入 `pyproject.toml`/`uv.lock`;请用 `uv sync --python 3.12`。其中 `langchain-community<0.4` 是为 RAGAS import 兼容性保留的 pin。
- 当前 eval 的端到端分数仍是 mock/rule-based 字段。进内网后再接 Copilot/gpt-5.5 judge、RAGAS、人工校准和真实质量闸门。
