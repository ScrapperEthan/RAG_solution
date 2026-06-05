# 交接说明(Handoff README)

> **一句话:** 这套 PoC 的代码分两手交接——**codex 在进内网前把能写的都写完(用 fake/本地等价物跑通),opencode 进内网后只把 4 个适配器换成真的。** 本文件告诉你谁读哪份、边界在哪。

---

## 1. 三个角色

| 角色 | 是谁 | 干什么 | 读哪份文档 |
|---|---|---|---|
| **codex** | 内网外的编码 agent(你用它写代码) | 写**进内网前能完成的全部代码**:后端 pipeline、eval harness、前端看板,全部用 fake/本地等价物跑通 | `01_CODEX_构建规格.md` |
| **opencode** | 内网内的编码 agent | 把 codex 留下的 **4 个适配器 stub** 换成真的(MCP / gpt-5.5 / 内网 embedding / 内网 pgvector),配好参数,跑真数据 | `02_OPENCODE_内网补充.md` |
| **你(Ethan)** | 执行层 | 把文档分别交给两个 agent;跑 SOP 闭环;守评测闸门 | 全部 |

---

## 2. 核心思路:端口与适配器(让 95% 的代码在内网外就能写完)

整个系统只有 **4 处**真正依赖内网。把它们抽象成"端口(interface)",其余代码全部面向端口编程,就能在内网外用 fake/本地等价物**端到端跑通**:

| 端口 | 内网外(codex 写,可跑) | 内网内(opencode 换) |
|---|---|---|
| `ConfluenceSource` | `FileConfluenceSource` 读 fixtures 假页 | `McpConfluenceSource` 走真 MCP |
| `LLM` | `MockLLM`(确定性) / 任意 OpenAI 兼容本地模型 | `Gpt55LLM` 指向内网 gpt-5.5 |
| `Embedder` | `HashEmbedder` 确定性离线实现(无需下载模型) | 内网部署的 embedding(可换 BGE-m3/内部模型) |
| `VectorStore` | `JsonVectorStore` 离线实现(无需 Docker) | 指向内网已有 pgvector/数据库服务,或先继续用 JSON store dry run |

> **关键结论:** 内网没有 Docker,启动方式按 `uv sync` / `uv run`。codex 先用 JSON store + hash embedding 把链路跑通;opencode 进内网后只替换 MCP / gpt-5.5 / embedding / store 适配器与配置。

```
                     ┌──────── 面向端口的核心代码(codex 全部完成,内网外跑通)────────┐
  Confluence ──►(ConfluenceSource)──► ingest/chunk ──► map ──► reduce ──► (VectorStore) ──►
                                                                              检索 ──► 作答 ──► eval ──► 看板
   (LLM) 在 map/reduce/作答/judge 处被调用    (Embedder) 在 load/检索处被调用
                     └────────────── 4 个端口的实现在内网外是 fake/本地,内网内换真 ──────────────┘
```

---

## 3. 工作流(你怎么用这套文档)

1. 把整个 `RAG_solution/` 仓库 + `01_CODEX_构建规格.md` 交给 **codex** → 它产出可运行(基于 fixtures)的前后端代码 + 一份 eval 报告样例 + 看板。
2. 你把仓库带进内网,把 `02_OPENCODE_内网补充.md` 交给 **opencode** → 它实现 4 个 adapter、配置、在 `2026 Planned Project` 切片上跑真数据。
3. 出真 eval 结果 → 看板展示(给领导看)→ 过闸门(卡片层 > baseline)→ 按 `card_ingestion_sop/` 的 SOP 跑 Business 评审与 bad-case 闭环 → 扩下一个切片。

---

## 4. 当前外网交付状态(给 opencode 先校准预期)

外网仓库当前能用 `fixtures/` 跑通一条完整 mock 链路:`ingest → map → reduce → load → eval → frontend`。这说明端口、产物格式、看板和回归测试可运行,但不代表真实业务指标已经成立。

已在外网完成:

- `map/reduce/answer/agentic` 已经通过 `LLM.complete_json` 端口调用;本地是 deterministic `MockLLM`,内网只需要把 LLM adapter 换成 Copilot / gpt-5.5 调用。
- `chunk` 已补代码围栏保护、可选小段合并、大段 block split + overlap。当前配置为保持 fixture section id 稳定,真实数据可调参数后重建 golden。
- schema 校验和回归测试覆盖关键产物与已知 bad cases。
- 前端可静态读取 `outputs/eval_report.json` 演示。

仍然不能在外网完成:

- 真实 Confluence MCP、Copilot/gpt-5.5、内网 embedding、内网 pgvector/Chroma 效果验证。
- 正式 30-50 题 golden、RAGAS judge、人工校准和 Business 质量闸门。当前 15 题只作为 fixture regression。
- “卡片层是否跑赢 baseline”的真实结论。这个必须以内网真实切片和冻结 golden 为准。

---

## 5. 仓库里已有的上下文(codex/opencode 都应先读)

| 文件 | 作用 |
|---|---|
| `RAG_PoC_Implementation_Spec.md` | 检索/切块/字段/DB/评测的**实现 spec**(权威技术细节) |
| `card_ingestion_sop/README_数据摄取卡片SOP.md` | 卡片 SOP 总览(map/reduce/卡片/闭环) |
| `card_ingestion_sop/skills/card-map/SKILL.md` | map 逐页抽取规则 + 输出 schema + prompt |
| `card_ingestion_sop/skills/card-reduce/SKILL.md` | reduce 合并/归一化/冲突规则 + schema + prompt |
| `card_ingestion_sop/templates/*` | 受控词表 / bad-case 库 / Business 评审清单 |
| `Confluence_QA_PoC_方案讨论稿.md` | 三方案 + agentic 下钻 + 评测指标(`association recall`/`漏钻率`)的来由 |
| `fixtures/` | 测试用假 Confluence 页(11)+ 起步 golden(15);codex 端到端跑通用,见 `fixtures/README.md` |

> **本 handoff 文档不重复上面的领域细节**,只给工程结构、端口设计、eval/前端实现、mock 与验收。领域规则一律指回上面的文件。

---

## 6. 文档清单

- `00_交接说明_README.md` —— 本文件(索引 + 边界)
- `01_CODEX_构建规格.md` —— 给 codex 的完整构建规格(主文档)
- `02_OPENCODE_内网补充.md` —— 给 opencode 的内网适配清单
