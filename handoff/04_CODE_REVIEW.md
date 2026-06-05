# CODE REVIEW —— 给 codex 的整改清单

> **读者:** codex(内网外编码 agent)。
> **背景:** 第一版骨架已交付并能离线确定性跑通,质量不错。本清单是进内网前的整改项。
> **总原则(重要):** **能在外网改的全部在外网改完**。下面每条都标了「在哪改」;凡标 `外网` 的都请你现在改掉。只有"用真 gpt-5.5 / 真 embedding / 真 RAGAS / 真 Confluence 数据跑出最终数字"这类**本质依赖内网**的,才留给 opencode。
> **底线:** 改完后 `python -m backend.pipeline demo` 仍要**确定性通过**(连跑两遍指标一致),并补上对应测试。

---

## 0. 验收总则

- 默认配置(file + mock + hash + json)的 `demo` 一键跑通且确定性不变。
- 新增/修改逻辑都要有单测;`backend/tests/` 绿。
- 看板在"合成数据"下必须显示 DEMO 横幅(见 CR-1)。
- 任何内网密钥/地址都不得进 git(见 CR-7)。

---

## 1. 严重度 × 在哪改 一览

| ID | 严重度 | 在哪改 | 一句话 |
|----|--------|--------|--------|
| CR-1 | 🔴 | 外网(主)+ 内网 | demo 数字是"管道自检"不是效果证据:加 DEMO 横幅、`local` 改真 BGE-m3、接真 RAGAS 代码路径 |
| CR-2 | 🔴 | 外网 | 真实 LLM prompt 没接,智能写在 MockLLM 启发式里;把 skill 完整 prompt 写进各 system |
| CR-3 | 🟡 | 外网建机制 / 内网验质量 | reduce 不发现新概念,词表硬编码 7 条种子;实现聚类+proposed+漏列发现 |
| CR-4 | 🟡 | 外网 | 概念过度关联污染卡片;归类改"本段主旨"而非"提及即归" |
| CR-5 | 🟡 | 外网 | rerank 是 no-op,V6=V5;用开源 reranker 真正实现 |
| CR-6 | 🟢 | 外网 | summary 节点复用 ref_id 会撞;独立 id 空间 |
| CR-7 | 🟢 | 外网 | config.yaml 未 gitignore + 文档示例 inline api_key;改 env + 忽略 |
| CR-8 | 🟢 | 外网 | 冲突取新用字符串比 update_at;解析成 datetime |
| CR-9 | 🟢 | 外网 | recall@8 实为 hit@8;统一口径/命名 |
| CR-10 | 🟢 | 外网 | 小瑕疵:troubleshoot 字段混 narrative 进 inline-value 等 |

> 一句话:**CR-1 的 b/c 与 CR-2~CR-10 全部外网可改**。只有 CR-1 最后一步(真模型/真数据出对外数字)、CR-3 的质量验证留内网。

---

## 2. 逐条详述

### CR-1 🔴 demo 数字非效果证据(别让看板误导)
**问题**:`embedder_hash.py`(hash 词袋)+ `MockLLM` + `eval/metrics.py`/`eval/service.py` 里把 `faithfulness/answer_relevancy/context_*` 用 `hit@8 → 0.95/0.45` 公式合成。所以看板分数无意义,且现状"纯 RAG 0.93 > 卡片 0.53"会让人误判卡片更差。

**外网改:**
- **(a) 看板 DEMO 横幅** `frontend/`:当 `report.embedding_model` 含 `hash` 或 `report.judge == "mock"` 时,页顶显示醒目 banner:「DEMO / 合成数据 —— 非真实评测结果,仅验证流程」。真实运行(非 hash、judge=gpt-5.5)时自动隐藏。
- **(b) 让 `local` 名副其实** `factory.py` 现在 `local → HashEmbedder`(名不副实)。新增真正的 `adapters/embedder_local.py`:用 `sentence-transformers` 加载 **BGE-m3**(1024 维),`provider: local` 指向它;`hash` 保留为无依赖兜底。把它加进 `pyproject` 可选依赖组。这样外网 demo 也能用**真 embedding**,数字才有参考价值。
- **(c) 接真 RAGAS 代码路径** `eval/`:把 `faithfulness/answer_relevancy/context_precision/context_recall` 从合成公式换成 RAGAS 实做;judge 走 `LLM` 端口(外网可指向任意 OpenAI 兼容模型联调)。`recall@k/MRR/nDCG` 保留自实现。

**内网改(opencode):** 用真 gpt-5.5 judge + 内网 embedding + 真数据重跑,才产出可对外的数字。

**验收:** hash/mock 下看板显示 banner;切到 local+兼容 judge 时 banner 消失且分数来自 RAGAS 而非 hit@8 公式。

---

### CR-2 🔴 真实 LLM prompt 没接(opencode 的活被低估)
**问题**:`mapper/service.py:MAP_SECTION_SYSTEM`、`PAGE_SUMMARY_SYSTEM`、`reducer/service.py:REDUCE_NORMALIZE_SYSTEM`、`answer/service.py:ANSWER_SYSTEM`、`agentic/service.py:INTENT_SYSTEM` 目前都是一行标签。真正的抽取/归一化/作答智能写在 `MockLLM` 回调的 `mapper/extract.py`、`reducer/canonicals.py`、`answer/service.py:synthesize_answer` 里——这些是对着 fixtures 调的,**换 gpt-5.5 后不会生效**。

**外网改:** 把 skill 的**完整 prompt** 写进上述各 `*_SYSTEM`:
- map → `card_ingestion_sop/skills/card-map/SKILL.md` §3.2
- reduce 归一化 → `card-reduce/SKILL.md` §3.1
- answer / 拒答 → `RAG_PoC_Implementation_Spec.md` §9
- intent / 下钻 → `Confluence_QA_PoC_方案讨论稿.md` §6.3
- **保留每段开头的 `task: xxx` 标签行**,MockLLM 靠它做子串路由(`llm_mock.py`),改了会断离线 demo。

**验收:** 切 `providers.llm: openai_compat` 指向任意兼容模型能产出合规 JSON;MockLLM demo 仍确定性通过。

---

### CR-3 🟡 reduce 不发现新概念(真实数据会塌)
**问题**:`reducer/canonicals.py:CANONICALS` 硬编码 7 条;`canonical_ids_for` 关键词规则映射;`reducer/service.py` 里 `if not cids: continue` 把未命中的 section **静默丢弃**。真实数据里新概念进不了卡片,也不进 review_queue(漏列 topic 发现没实现),违背"词表自底向上生长"。

**外网改(建机制):** 实现 `card-reduce/SKILL.md` §2 step1.3:未命中现有 canonical 的关键词 → 聚类成 `status=proposed` 新概念 + `needs_review`;高频未归类词进 review_queue(漏列发现)。用 MockLLM 对 fixtures 返回确定性聚类。删掉静默丢弃。

**内网改:** 真 gpt-5.5 跑聚类质量。

**验收:** 在 fixtures 里放一个不在 CANONICALS 的伪概念,reduce 能产出 proposed 词条 + review_queue 项,不再静默丢。

---

### CR-4 🟡 概念过度关联,卡片被污染
**问题**:`canonical_ids_for` 只要 section 文本"出现"某词就归该概念。一句 "see the Journey page" 的交叉引用,把该段同时塞进 DM/Journey/Adaptor 三张卡。`outputs/cards/DM_Plugin.json` 的 `definition` 因此拼进了 Adaptor / WoW / Journey 等 12 段无关摘要。

**外网改:** 归类改"本段主旨":只在概念出现在 `heading_path` / map 产物的 `concepts` 字段、或为该段主关键词时归入;交叉引用("see / refer to X")不计入归属,只走 `soft_links`。

**验收:** DM_Plugin 卡 `definition` 不再混入无关页;`sources` 回落到真正讲 DM 的段。

---

### CR-5 🟡 rerank 是 no-op
**问题**:`retrieve/service.py` 无 rerank 步骤;`variants.py` 里 V6 标 `rerank: true` 但结果与 V5 完全相同。spec 把 rerank 列为性价比最高的杠杆。

**外网改:** 实现真 rerank:`bge-reranker-v2-m3`(cross-encoder,开源可离线),在 RRF 融合后按 `(query, ref.body_md)` 重排;`config.retrieval.rerank` 开关生效。无该依赖时给确定性回退并在报告标注 `rerank: placeholder`。

**验收:** V6 与 V5 结果不同(rerank 真的动了)。

---

### CR-6 🟢 summary 节点 ref_id 撞
**问题**:`load/service.py:build_summaries` 让 summary 的 `ref_id` = 该页首个 ref 的 id;`retrieve` 把 summaries 命中混进 RRF,`get_refs` 按 refs 表回取会错位(summary 命中被当成那个 ref)。

**外网改:** summaries/descriptions 用独立 id 命名空间(如 `s{n}` / `d{n}`),RRF 按 `(table, id)` 唯一;检索层能正确把 summary 命中展开为其页的 refs(spec §9 "summary hits expand to their page's refs")。

**验收:** drilldown 里 summary 命中显示正确来源,不被误当某个 ref。

---

### CR-7 🟢 密钥 / gitignore
**问题**:`.gitignore` 未含 `config.yaml`;`handoff/02_OPENCODE` 示例把 `api_key` 写进 yaml,有提交明文风险。

**外网改:** `.gitignore` 加 `config.yaml`,提供 `config.example.yaml`;`OpenAICompatLLM` 已支持 `api_key_env`,把文档示例改成 `api_key_env: GPT55_API_KEY`(不要 inline)。

**验收:** config.yaml 不被 git 跟踪;示例无明文密钥。

---

### CR-8 🟢 冲突取新用字符串比较
**问题**:`reducer/service.py:merge_config_field` 按 `(update_at, version)` 字符串排序取新。fixtures 统一 ISO+Z 没事,真 Confluence 时区/格式不一可能比错。

**外网改:** 解析 `update_at` 为 `datetime`(带回退)后比较。

**验收:** 乱序/不同格式时间戳也能正确取新值。

---

### CR-9 🟢 recall@8 实为 hit@8
**问题**:`eval/metrics.py` 里 `recall@8` 是"命中即 1",多跳题的完整度在 `context_recall` 里。命名易让人(尤其领导)高估多跳。

**外网改:** 二选一——真算 recall(命中比例),或把标签改 `hit@8` 并在看板注明口径。

**验收:** 口径清晰,多跳不被高估。

---

### CR-10 🟢 小瑕疵
- `reducer/service.py:build_card` 的 `troubleshoot` 字段把 narrative 填充("FAQ covers ... (narrative)")混进 `tier: inline-value`;拆分或正确标 tier。
- `ingest/chunk.py` 大段二次切分给 heading 加 `(part N)` 会改 `section_id`(目前 `min_merge_tokens=0` 规避,config 已注释)。真实切片调大该值时,记得**重新生成 golden 的 section id**(spec/配置注释已提示,补一句到 02 文档)。

---

## 3. 改完后(外网)应达到的状态

- `demo` 默认(hash/mock)仍确定性通过;看板显示 DEMO 横幅。
- 切 `providers: local + openai_compat`(指任意兼容模型)能跑出**真 embedding + 真 RAGAS** 的一版数字(用于外网联调,不代表内网最终结果)。
- 各 `*_SYSTEM` 已是 skill 完整 prompt;reduce 能产出 proposed 新概念;rerank 真实生效;summary 路由正确;无明文密钥。
- 新增测试覆盖:DEMO 横幅触发、新概念发现、rerank 改变排序、datetime 取新、summary 命中回取。

## 4. 仍留给内网(opencode,本质依赖内网)

- `McpConfluenceSource` 真 MCP 抓取;`Gpt55LLM` 指向内网 gpt-5.5;内网 embedding(若 ≠ BGE-m3);pgvector DSN。
- 用真 gpt-5.5 judge + 真数据跑出**对外可用的最终评测数字**,过质量闸门(`association_recall` / `漏钻率` / 卡片层 > baseline)。
- reduce 新概念聚类的**质量**验证 + Business 评审闭环。
