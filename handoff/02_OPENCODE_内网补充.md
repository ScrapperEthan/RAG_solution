# OPENCODE 内网补充文档(Intranet Fill-in)

> **读者:** opencode(内网内编码 agent)。
> **你接手时的状态:** codex 已交付一个**可运行**的系统——后端 pipeline、eval harness、前端看板,全部用 fake/本地实现在内网外跑通过(基于 `fixtures/`)。端口、产物格式、mock 回归链路已完成;正式业务效果、RAGAS judge、真实 golden 和质量闸门必须以内网真实数据重跑为准。
> **你的使命:** 把 4 个**适配器 stub** 换成真的内网实现,配好参数,在真实 Confluence 切片上跑出真结果。**不要改业务逻辑**——只填端口实现 + 配置。
> **先读:** `00_交接说明_README.md`、`01_CODEX_构建规格.md` §2(端口定义)、`03_OPENCODE_RAGAS_CHROMA.md`,以及 `RAG_PoC_Implementation_Spec.md`、`card_ingestion_sop/`。

---

## 1. 你只需要做四件事(端口实现)+ 配置

所有业务代码都面向 `backend/ports.py` 的接口编程,实现都在 `backend/adapters/`。你按下表把 4 个 stub 填实,改 `config.yaml` 切换 provider 即可,**其余一行不用动**。

| # | 端口 | stub 文件 | 你要做的 | 验证 |
|---|---|---|---|---|
| 1 | `ConfluenceSource` | `adapters/confluence_mcp.py` | 用内网 Confluence **MCP** 实现 `list_pages(slice_root)`(按页树枚举切片子树)+ `get_page(page_id)`(返回 `RawPage`:metadata + Markdown 正文;**把夹在标题/正文间的 `tree_path` 解析进字段**)。图片按本地路径处理(spec §5)。 | 抓 `2026 Planned Project` 子树,页数与 Confluence 一致;`tree_path` 解析正确 |
| 2 | `LLM` | `adapters/llm_gpt55.py` | 指向内网 **gpt-5.5**。大概率是 OpenAI 兼容协议——优先复用 codex 写的 `OpenAICompatLLM`,只配 `base_url/model/api_key`;若协议不同再实现 `complete_json`(注意**强制返回严格 JSON**、失败重试、`temperature=0`)。 | 用 map prompt 抽一页,JSON 校验通过 |
| 3 | `Embedder` | `adapters/embedder_intranet.py` | 接内网可用的 embedding 服务/模型。若暂时没有,可先用 `providers.embedder: hash` 做 dry run。**关键:`dim` 必须与 store 中向量维度一致**;超 2000 维改 `halfvec`(spec §7 注)。查询语言多语种(spec §8)。 | embed 一批文本,维度正确;跨语种检索可用 |
| 4 | `VectorStore` | `adapters/store_chroma.py` / `adapters/store_pgvector.py` / `adapters/store_json.py` | 内网**没有 Docker**。优先用 Chroma 快速验证;若已有 pgvector/数据库服务,再实现/配置 `store_pgvector.py` + DSN;若依赖受限,先用 `JsonVectorStore` 跑通业务链路和 eval。 | `load` 成功;retrieve/answer 可读回 refs |

> **依赖注入:** 改 `config.yaml → providers`:`confluence: mcp`、`llm: gpt55`(或 `openai_compat`)、`embedder: intranet`(或先 `hash`)、`store: chroma`(或 `pgvector` / `json`)。`factory.py` 自动装配。

---

## 2. 配置清单(`config.yaml`)

把这些值落实(codex 已留好键位与默认):

```yaml
providers: {confluence: mcp, llm: gpt55, embedder: intranet, store: chroma}   # 有真实 DB 后可切 store: pgvector

slice:
  root: "06-Delivery/10. Planned Project/2026 Planned Project"

confluence_mcp: {endpoint: "<内网 MCP>", space: "<DEPT>", auth: "<...>"}
llm:            {base_url: "<内网 gpt-5.5>", model: "gpt-5.5", api_key: "<...>", temperature: 0}
embedder:       {model: "<内网 embedding 或 bge-m3>", dim: 1024}
store:          {path: "outputs/store/store.json", chroma_path: "outputs/chroma", dsn: "postgresql://<内网 pgvector 如可用>"}
retrieval:      {index: both, search: hybrid, top_k: 8, rrf_k: 60, rerank: true, reranker: bge-reranker-v2-m3}
generation:     {require_citations: true, refuse_when_no_context: true}
eval:           {golden_size: 50, judge: gpt-5.5, framework: ragas}
```

启动方式:

```powershell
uv sync
uv run python -m backend.pipeline demo
uv run python -m backend.pipeline ingest
uv run python -m backend.pipeline map
uv run python -m backend.pipeline reduce
uv run python -m backend.pipeline load
uv run python -m backend.pipeline eval
```

---

## 3. 运行顺序(spec §13 里程碑)

```
1) ingest   抓切片子树 → outputs/capture/         # 先 eyeball 5–10 页切块质量
2) map      逐页抽取    → outputs/map/
3) reduce   合并归一化  → outputs/cards/ + inverted_index + review_queue
4) load     embed+落库  → JSON store 或内网 pgvector(refs/descriptions/summaries + tsvector)
5) retrieve/answer       # 抽样问几个问题,人工看检索与引用对不对
6) eval     生成冻结 golden → 跑变体矩阵 → outputs/eval_report.json
7) 前端看板  读 eval_report.json 展示(给领导)
```

---

## 4. 验证与质量闸门(别跳过)

- **golden 解耦**:确认评测题用的是**与索引/卡片不同的 prompt**、来源是**留出原文**而非卡片——否则 recall/`association_recall` 虚高(spec §11.1 红线)。
- **judge 校准**:LLM-as-judge 用 gpt-5.5 前,先拿 ~10 条人工标注校准,防裁判有偏(spec §11.2)。
- **闸门**:卡片层只有在冻结 golden 上**跑赢纯 RAG baseline** 才采纳;重点看 `association_recall`(补漏页是否有效)与 `漏钻率`(精确题是否该下钻而没下钻)。不达标 → 进 bad case 找因,别硬堆卡片。
- **增量幂等**:页 `confluence_version` 变 → 只重跑该页 map → 只对受影响概念 reduce,别全量重算(讨论稿 §5.5)。

---

## 5. 跑通之后:接上 SOP 闭环

真数据出来后,这套就进入 `card_ingestion_sop/` 的持续优化回路:

- 把 `inverted_index` + `review_queue` + 卡片抽样,按 `templates/business_review_checklist_评审清单.md` 批量交 Business 审(精度/召回/裁决)。
- 反馈 → 更新 `canonical_keywords_受控词表.md`(approved/merged)+ 登记 `bad_case_library_纠错案例库.md` → 提炼规则回写 `card-map/card-reduce` skill → 加入**回归集**重跑。
- golden set(测效果)与回归集(测 skill 行为)**两套都跑,别混**。
- 过闸门 → 扩下一个切片。

---

## 6. 边界提醒

- **只填端口 + 配置,不改业务逻辑。** 若发现业务代码有 bug,记一条 issue 回传,而不是绕过端口私改(否则内网外的可重复性就废了)。
- 内网密钥/地址只进 `config.yaml`(或环境变量),**不要硬编码进代码**。
- embedding 维度一旦定下,与 pgvector 建表维度必须一致;中途换模型要重建向量列并重嵌。
