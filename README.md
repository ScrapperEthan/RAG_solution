# Confluence RAG / Card PoC

本仓库是一套可在内网外离线跑通、再由 opencode 在内网接入真实依赖的 Confluence RAG PoC。

系统包含：

- Confluence 摄取、结构化切块、Map/Reduce 卡片生成
- 外部审批词表与多标签 `module` facet
- 向量、全文、RRF、rerank 检索
- 卡片直答、回原文 grounding、纯 RAG fallback
- 路径感知的 Web 问答：RAG / LLM + Wiki（审批卡片）/ Agentic 三族按实际执行路径展示不同 trace
- Golden Set 与变体评估
- 流式问答前端和完整评估看板

> 本地默认配置使用 fixture Confluence、`MockLLM`、hash embedding 和 JSON store。它只用于验证代码链路，不代表真实业务效果。

---

## Opencode 接手前必须先读

**Opencode 不要拿到仓库后直接修改代码或运行真实数据。必须先阅读 `handoff/`。**

按以下顺序阅读：

1. [`handoff/00_交接说明_README.md`](handoff/00_交接说明_README.md)
   先理解角色、边界、端口架构和交付状态。
2. [`handoff/01_CODEX_构建规格.md`](handoff/01_CODEX_构建规格.md)
   理解完整架构、业务链路、产物和端口定义。
3. [`handoff/02_OPENCODE_内网补充.md`](handoff/02_OPENCODE_内网补充.md)
   **Opencode 的主要执行手册**：内网需要补什么、配置什么、如何验收。
4. [`handoff/03_OPENCODE_RAGAS_CHROMA.md`](handoff/03_OPENCODE_RAGAS_CHROMA.md)
   Python 3.12、Chroma 快速验证和 RAGAS 接入说明。
5. [`handoff/04_CODE_REVIEW.md`](handoff/04_CODE_REVIEW.md)
   理解已整改内容、风险和仍留给内网的真实验证工作。
6. [`handoff/05_合并对接_module_facet.md`](handoff/05_合并对接_module_facet.md)
   **同事审批词表的接合契约**，以及 `module` 多标签、零删页规则。

然后再阅读：

- [`RAG_PoC_Implementation_Spec.md`](RAG_PoC_Implementation_Spec.md)
- [`card_ingestion_sop/`](card_ingestion_sop/)
- [`backend/ports.py`](backend/ports.py)
- [`config.example.yaml`](config.example.yaml)

`05_合并对接_module_facet.md` 对词表发现职责的说明优先于旧讨论：**topic/keyword discovery 由同事组件负责，本项目只读取 Business 已审批的词表，不自行创建 topic。**

### 可直接交给 opencode 的开场指令

```text
先不要改代码。请按 README 指定顺序阅读 handoff/00 到 handoff/05，
再阅读 RAG_PoC_Implementation_Spec.md、card_ingestion_sop/ 和 backend/ports.py。

完成阅读后：
1. 先运行离线测试，确认当前基线；
2. 只实现或配置内网端口适配器，不绕过现有业务逻辑；
3. 使用同事提供并经 Business 审批的 keyword_table；
4. 按 ingest -> map -> reduce -> load -> retrieve/answer -> eval 分步验证；
5. 不得把内网地址、密钥或真实数据提交到 git；
6. 最终提交真实数据运行结果、坏案例、评估报告和仍未解决的问题。
```

---

## 架构与责任边界

核心业务代码面向四个端口编程：

| 端口 | 本地离线实现 | 内网目标 | Opencode 工作 |
|---|---|---|---|
| `ConfluenceSource` | `FileConfluenceSource` | 真 Confluence MCP | 实现 `McpConfluenceSource` |
| `LLM` | `MockLLM` | 内网 gpt-5.5 / Copilot | 优先配置 `OpenAICompatLLM` / `Gpt55LLM`；协议不兼容时再改 adapter |
| `Embedder` | `HashEmbedder` / 本地 BGE | 内网 embedding | 实现或配置 `IntranetEmbedder`，保证维度一致 |
| `VectorStore` | `JsonVectorStore` / Chroma | Chroma 或已有 pgvector | 配置现有 adapter 和 DSN；不要在代码里直连数据库 |

核心链路：

```text
Confluence
  -> ingest / chunk
  -> map
  -> reduce + approved keyword table
  -> cards + inverted index + review queue
  -> load refs / descriptions / summaries
  -> retrieve / answer / agentic routing
  -> eval
  -> streaming Q&A + evaluation dashboard
```

Opencode 原则：

- 只通过 `backend/ports.py` 和 `backend/adapters/` 接内网能力。
- 不要为了跑通而绕过 schema、grounding、review queue 或评测逻辑。
- 发现核心业务 bug 时记录并修复根因，不在 adapter 中偷偷改变业务语义。

### 当前实现边界

- 当前 Web API 使用 NDJSON 流式事件，但回答文本是在完整答案返回后分块推送。若领导演示要求真实首 Token 延迟，opencode 需要为内网 LLM adapter 增加 provider-native streaming，同时保持现有非流式端口兼容。
- `LLM + Wiki` 在本项目中明确指审批后的结构化 Card，可选择卡片直答或沿来源锚点回原文取证。
- `模型直答 · 无 grounding 基线` 只通过当前 `LLM.complete_text` 端口调用连接模型，不代表 Wiki，也不会伪造检索证据或引用。
- Pipeline 当前通过 CLI 手动分步执行，不包含定时调度或生产级任务编排。
- 本地 `eval` 的 mock 分数只用于回归；RAGAS 接口已经存在，但必须使用真实模型、真实 embedding、真实数据和人工校准后重新验证。
- `config.example.yaml` 是配置模板，不是可直接使用的内网配置。opencode 必须根据 `handoff/02` 修改 provider 和内网参数。

---

## 本地快速开始

### 1. 环境

推荐使用 Python 3.12。不要使用 Python 3.14，部分 RAGAS 依赖在 Windows 上可能需要本地编译。

```powershell
uv sync --python 3.12
```

需要本地 BGE/reranker：

```powershell
uv sync --python 3.12 --extra local --extra rerank
```

需要已有 pgvector 服务：

```powershell
uv sync --python 3.12 --extra pgvector
```

### 2. 跑离线 Demo

确认当前目录没有指向真实内网环境的 `config.yaml`，再运行：

```powershell
uv run python -m backend.pipeline demo
```

默认读取：

- `fixtures/confluence/*.md`
- `fixtures/keyword_table.jsonl`
- `fixtures/golden_seed/golden_seed.jsonl`

并使用：

- `providers.confluence: file`
- `providers.llm: mock`
- `providers.embedder: hash`
- `providers.store: json`

> **警告：`demo` 会清理 `outputs/` 下的已有产物，Chroma 目录除外。它只适用于离线自检。接入真实数据后不要使用 `demo`，应分步运行 pipeline。**

查看产物状态：

```powershell
uv run python -m backend.pipeline status
```

### 3. 启动演示前端

```powershell
uv run python -m backend.web --host 0.0.0.0 --port 8765
```

本机访问：

```text
http://localhost:8765/
```

内网其他同事访问：

```text
http://<运行服务的机器IP>:8765/
```

前端包含两个页签：

- **实时问答**：Golden Set 对比、自由提问、流式 LLM Answer、检索证据、module 筛选。
- **评估看板**：Overview、Variant Ladder、完整指标表、Card Value、Golden Types、Question Drilldown、筛选和打印。

Web 服务不会自动运行 pipeline，也不会自动生成评估数据：

- 没有 `outputs/eval_report.json`：看板显示未生成。
- 真实模型/judge 报告：自动加载。
- `mock` judge 或 `hash` embedding 报告：默认拦截，必须点击“明确加载 Demo 数据”。
- mock/hash provider 下页面始终显示 Demo 标识。

---

## Pipeline 命令

分步运行：

```powershell
uv run python -m backend.pipeline ingest --config config.yaml
uv run python -m backend.pipeline map --config config.yaml
uv run python -m backend.pipeline reduce --config config.yaml
uv run python -m backend.pipeline load --config config.yaml
uv run python -m backend.pipeline retrieve --config config.yaml --query "DM plugin default batch_size?"
uv run python -m backend.pipeline answer --config config.yaml --query "DM plugin default batch_size?"
uv run python -m backend.pipeline eval --config config.yaml
uv run python -m backend.pipeline status --config config.yaml
```

按 module 检索：

```powershell
uv run python -m backend.pipeline retrieve `
  --config config.yaml `
  --query "default batch_size" `
  --filter "module=Delivery & tracking standard"
```

`module` 是多标签 facet，只用于导航和可选检索过滤：

- 一个 page/section/card 可以属于多个 module。
- module 不得用于删除或跳过页面。
- 低价值页面使用 `card_worthy=false` 标记，但仍保留给 RAG。

使用 Chroma 做离线快速验证：

```powershell
uv run python -m backend.pipeline demo --config config.chroma.yaml
uv run python -m backend.pipeline retrieve --config config.chroma.yaml --query "DM plugin default batch_size?"
```

---

## 主要产物

| 路径 | 内容 |
|---|---|
| `outputs/capture/` | Confluence 原始抓取与切块结果 |
| `outputs/map/` | 逐页结构化 Map 结果 |
| `outputs/cards/` | 跨页 Reduce 后的 topic cards |
| `outputs/cards_index.json` | 卡片索引 |
| `outputs/inverted_index.jsonl` | topic 到 page/section 的倒排关系 |
| `outputs/review_queue.jsonl` | 未匹配、冲突、低置信度等待人工处理的问题 |
| `outputs/loaded_refs.json` | 待写入 store 的原文章节 |
| `outputs/loaded_descriptions.json` | 假设问题/description 索引 |
| `outputs/loaded_summaries.json` | 页面 summary 路由索引 |
| `outputs/store/` / `outputs/chroma/` | 本地向量存储 |
| `outputs/golden_set.json` | 冻结后的 Golden Set 与 hash |
| `outputs/eval_report.json` | 前端评估看板读取的报告 |
| `outputs/eval_report.md` | 人可读评估摘要 |

`section_id` 由 page 和 heading 共同组成。修改 chunk 参数，特别是大段切分规则后，section ID 可能变化，必须同步重建 Golden Set。

---

## 配置

`config.yaml` 已被 `.gitignore` 忽略。不要提交真实内网配置。

复制示例：

```powershell
Copy-Item config.example.yaml config.yaml
```

内网目标配置示意：

```yaml
providers:
  confluence: mcp
  llm: gpt55          # OpenAI-compatible 时也可使用 openai_compat
  embedder: intranet  # 没有内网 embedding 时可先用 local/hash dry run
  store: chroma       # 有现成 pgvector 服务后可切 pgvector

slice:
  root: "06-Delivery/10. Planned Project/2026 Planned Project"

paths:
  golden_seed: inputs/golden_seed.jsonl
  outputs_dir: outputs
  keyword_table: inputs/keyword_table.jsonl

llm:
  base_url: "<内网 OpenAI-compatible endpoint>"
  model: "gpt-5.5"
  api_key_env: GPT55_API_KEY
  temperature: 0.0

embedder:
  model: "<内网 embedding 或 BAAI/bge-m3>"
  dim: 1024

store:
  path: outputs/store/store.json
  chroma_path: outputs/chroma
  dsn: "postgresql://<已有 pgvector 服务>"

retrieval:
  index: both
  search: hybrid
  top_k: 8
  rrf_k: 60
  rerank: true

eval:
  judge: gpt-5.5
```

密钥只通过环境变量提供：

```powershell
$env:GPT55_API_KEY = "<secret>"
```

不要把密钥、token、内网 URL、真实 Confluence 内容或真实评估报告提交到 git。

---

## Opencode 内网执行清单

### 阶段 0：建立基线

完成 handoff 阅读后，**在创建真实 `config.yaml` 之前**先验证传入仓库没有损坏：

```powershell
uv sync --python 3.12
uv run python -m unittest discover -s backend/tests
uv run python -m backend.pipeline demo
```

离线 demo 应确定性通过。当前测试同时覆盖 pipeline、module facet、pgvector filter、Web API、mock 报告拦截等行为。

### 阶段 1：准备同事输入

从同事处取得 Business 审批后的 `keyword_table`，推荐放到：

```text
inputs/keyword_table.jsonl
```

必须确认：

- 只使用 `status=approved` 的行。
- `topic`、`canonical_id`、`aliases`、`module`、`related page` 等字段满足 `handoff/05` 契约。
- `aliases` 缺口已经解决，否则 `DMP`、`Data Management` 等原文叫法无法归入规范 topic。
- `module` 是数组/多标签。
- 不得因 module 或 `card_worthy=false` 删除页面。

### 阶段 2：接入四个端口

1. [`backend/adapters/confluence_mcp.py`](backend/adapters/confluence_mcp.py)
   实现子树枚举和页面抓取，正确填充 `RawPage`、`tree_path`、版本和来源 URL。
2. [`backend/adapters/llm_gpt55.py`](backend/adapters/llm_gpt55.py)
   如果内网接口兼容 OpenAI Chat Completions，通常只需要配置；否则在 adapter 内适配协议。
3. [`backend/adapters/embedder_intranet.py`](backend/adapters/embedder_intranet.py)
   实现 query/passage embedding，确认多语种能力和向量维度。
4. [`backend/adapters/store_chroma.py`](backend/adapters/store_chroma.py) / [`backend/adapters/store_pgvector.py`](backend/adapters/store_pgvector.py)
   优先用 Chroma 跑通，再根据现有基础设施切 pgvector。内网无 Docker，不要把 Docker 作为前置条件。

### 阶段 3：按步骤跑真实数据

不要直接执行 `demo`。逐步运行并在每一步人工抽检：

```powershell
uv run python -m backend.pipeline ingest --config config.yaml
uv run python -m backend.pipeline map --config config.yaml
uv run python -m backend.pipeline reduce --config config.yaml
uv run python -m backend.pipeline load --config config.yaml
uv run python -m backend.pipeline retrieve --config config.yaml --query "<抽样问题>"
uv run python -m backend.pipeline answer --config config.yaml --query "<抽样问题>"
uv run python -m backend.pipeline eval --config config.yaml
```

人工检查重点：

- `capture` 页数与 Confluence 子树一致，`tree_path` 正确。
- 抽查 5–10 页的 heading、切块、表格和代码块。
- Map 输出通过 schema，事实值和 pointer tier 正确。
- Reduce 只使用审批词表；未命中内容进入 `review_queue`。
- 卡片、倒排、refs 中的 module 都是多标签。
- 所有页面仍可从 RAG 检索，零删页。
- 答案有来源，缺少依据时拒答。

### 阶段 4：真实评测与质量闸门

- 使用真实 holdout 原文制作并人工检查 Golden Set，不要把 fixture 15 题当正式 Golden。
- Golden Set 与索引/卡片生成过程解耦。
- 使用真 gpt-5.5 judge / RAGAS 前，先用约 10 条人工标注校准 judge。
- 卡片方案只有在冻结 Golden Set 上跑赢纯 RAG baseline 才能通过。
- 重点关注 `association_recall`、`drill_miss_rate`、faithfulness、context precision 和坏案例。
- 看板出现 Demo 横幅或要求“明确加载 Demo 数据”时，该报告不能作为对外效果证据。

### 阶段 5：启动内网演示

```powershell
uv run python -m backend.web --config config.yaml --host 0.0.0.0 --port 8765
```

验收：

- Golden Set 模式同时显示 Gold Answer 和流式 LLM Answer。
- 自由提问能够返回真实模型回答。
- 引用和检索证据能打开对应 Confluence 页面。
- module 筛选有效。
- 评估看板自动加载真实报告，不显示 Demo 警告。

---

## 与同事对接

### 同事需要提供

- Business 审批后的 `keyword_table.jsonl`
- aliases/同义词策略
- 多标签 module 值
- related pages 真值
- 真实 Confluence slice root 和访问权限
- 用于 Golden Set 的 holdout 原文与人工确认

### Opencode 需要回传

- 最终使用的本地 `config.yaml` 字段说明，但不包含密钥
- 四个内网 adapter 的实现状态
- 每一步 pipeline 的数量与抽检结果
- `review_queue` 和 bad cases
- 真实 Golden Set 的来源、冻结 hash 和人工检查记录
- `eval_report.json` / `eval_report.md`
- 卡片方案与纯 RAG baseline 的对比结论
- 未解决问题和下一步建议

### 不能混淆的两套数据

- fixture/mock 数据：只证明代码链路可运行。
- 内网真实数据：才可用于业务效果判断和领导汇报。

---

## 测试

```powershell
uv run python -m unittest discover -s backend/tests
```

提交内网改动前至少还应验证：

```powershell
uv run python -m backend.pipeline status --config config.yaml
uv run python -m backend.pipeline retrieve --config config.yaml --query "<known-answer question>"
uv run python -m backend.pipeline answer --config config.yaml --query "<known-answer question>"
```

---

## 常见问题

### 没有 `config.yaml` 为什么还能运行？

`backend/config.py` 会回退到默认离线配置：file + mock + hash + json。这是为了本地自检，不是内网真实配置。

### 看板为什么不显示已有 mock 报告？

这是刻意的保护。mock/hash 报告默认被拦截，必须明确点击“加载 Demo 数据”，避免把合成分数误当真实效果。

### Web 服务会自动抓取或自动生成 eval 吗？

不会。Web 服务只读取现有 store、Golden Seed 和 `eval_report.json`。先运行对应 pipeline 步骤。

### 换 embedding 后为什么 load/retrieve 失败？

检查 `embedder.dim` 是否与 Chroma/pgvector 中已有向量维度一致。更换模型或维度后需要重建向量存储并重新 load。

### 调整 chunk 参数后为什么 Golden 命中下降？

chunk heading 和 `(part N)` 会改变 `section_id`。切块策略变更后必须重新制作并冻结 Golden Set。

### 内网接口不是 OpenAI-compatible 怎么办？

只在 `backend/adapters/llm_gpt55.py` 中适配协议，保持 `LLM.complete_json` / `complete_text` 端口契约，不要修改业务服务调用方式。

---

## 目录速览

```text
backend/
  adapters/       # 本地和内网端口实现
  ingest/         # 抓取与结构化切块
  mapper/         # 逐页 Map
  reducer/        # 审批词表归一化、卡片和 review queue
  load/           # refs/descriptions/summaries 写入 store
  retrieve/       # vector + FTS + RRF + rerank
  answer/         # grounded answer
  agentic/        # card / drill / RAG 路由
  eval/           # Golden Set、变体、指标和 RAGAS 接口
  schemas/        # 关键产物校验
  tests/          # 自动化测试
  web.py          # FastAPI、流式问答 API、前端服务
frontend/         # 无构建步骤的演示前端
fixtures/         # 离线 fixture、审批词表替身、Golden Seed
handoff/          # opencode 必须先读的交接文档
card_ingestion_sop/
outputs/          # pipeline 生成产物
```
