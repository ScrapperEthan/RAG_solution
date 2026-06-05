# fixtures —— 测试用假数据(给 codex)

> **这是什么:** 一批"长得跟真 Confluence 一模一样"的**假页**,外加一份起步 golden set。
> codex 在内网外用它们把整条链(ingest→map→reduce→load→retrieve→answer→eval→看板)**端到端跑通**;进内网后,opencode 把数据源换成真 MCP,**同一套代码**跑真页。
> 这些假页**刻意埋了真实数据会出的坑**,跑一遍就能验证代码有没有正确处理(等于"已知正确答案"的测试)。

---

## 目录

```
fixtures/
├─ confluence/      # 11 个假 Confluence 页(.md:front-matter=metadata,正文=body_md)
├─ golden_seed/     # golden_seed.jsonl —— 15 题起步评测集(codex 扩到 ~50)
└─ llm_canned/      # 预留:如未来需要按 prompt hash 固定 MockLLM 返回,放这里
```

- `confluence/*.md` 由 `FileConfluenceSource` 读取(见 `handoff/01_CODEX_构建规格.md` §2)。front-matter 字段对应 `RawPage`;`tree_path` 已是数组(真实里它夹在标题/正文间,这里替你解析好了)。
- **section id 约定**:`page_id + "#" + 该 H2 标题`,例如 `123456#Configuration`。golden 的 `gold_section_ids` 用的就是这个格式;检索结果也要带同一格式的 id,recall 才算得出来。

---

## 11 个假页 + 每页埋的坑

| 文件 | 概念 | 埋的坑 / 测什么 | 对应 bad case |
|---|---|---|---|
| `123456_DM_Plugin_Overview.md` | DM Plugin | 别名 `DM plugin/Data Management/DMP`;精确值 `batch_size:500`、`max_retry:3`;指向 Journey(多跳) | `map-001`(别名归一化) |
| `777001_SFMC_Migration.md` | SFMC 迁移 | `batch_size:1000`,`update_at` 更晚 → 与 123456 的 500 **冲突**,应取新+标注 | `reduce-001`(冲突取新) |
| `220110_Journey_Plugin_Overview.md` | Journey Plugin | 多跳另一端(从 DM 经 adaptor 接收);精确值 `max_concurrent_journeys:50` | — |
| `305001_MDC_OTP_Service.md` | MDC OTP Service | `OTP` **歧义**(专指本服务 vs 泛指);精确值 `otp_length:6`、`otp_ttl:300` | RQ-0019(概念歧义) |
| `140020_Adaptor.md` | Adaptor | 拼写变体 `adaptor/adapter` → 归一化;DM↔Journey 关系 | 拼写别名 |
| `160033_Message_Inventory.md` | 消息清单 | 也提到 DM 批处理 → **应关联到 DM Plugin**(测 `association_recall` 的"漏页") | Business 评审"漏页"例 |
| `180044_Delivery_Way_of_Working.md` | 交付流程 | `content_type=process`,无精确插件值(增加广度 + 归属关系) | — |
| `190055_2026_Planned_Project_Overview.md` | 项目总览 | 架构全貌"DM→adaptor→Journey,OTP 另走" → 喂**多跳/页级 summary** | — |
| `200066_DM_Plugin_Troubleshooting.md` | DM 排障 | 错误码 `DM-429`;**"supports retry configuration"但不给数值** → `pointer-only`,值在 123456,测下钻/漏钻 | `map-002`(支持≠值) |
| `230088_Design_Decision_Single_Adaptor.md` | 设计决策 | `content_type=decision`;adaptor 关系的理由 | — |
| `210077_Supply_and_Demand.md` | 容量规划 | 邻近/无关内容 → 让部分问题**越界无答案**(测拒答) | out-of-scope |

> 坑全部来自 `card_ingestion_sop/`:bad case 库的 `map-001/map-002/reduce-001`、受控词表的 `OTP` 歧义(RQ-0019)、Business 评审清单里"Message Inventory 漏页"那个例子。跑 `uv run python -m backend.pipeline demo` 后,在卡片/倒排表/eval 里应能看到它们被正确处理。

---

## golden_seed.jsonl(15 题起步集)

- 每行一题:`q_id, q_en, q_zh, type, gold_section_ids, gold_answer, human_checked`。
- 覆盖五类:`single / multihop / identifier-lookup / pointer-drill / out-of-scope`。
- `gold_section_ids` 指向上面的真实 heading;越界题用字符串 `"NO_ANSWER"`。
- 几道关键题的用意:
  - `G-002`(batch_size 默认)gold = 迁移页(取新 1000),测**冲突取新**。
  - `G-004`(重试几次)gold = Configuration,测**漏钻**:排障页只说"可配 retry",真值在 Overview,agent 不下钻就答不准。
  - `G-010`(谁处理批次)gold 含 Message Inventory,测 **association_recall**(漏页有没有被关联回 DM)。
  - `G-011/012` 越界,测**拒答**(应答 NO_ANSWER,不编)。
- codex:把它当**起点**扩到 ~50 条(配比见 `01_CODEX_构建规格.md` §6.1),并保持**与索引/卡片 prompt 解耦**(spec §11.1)。

---

## codex 怎么用

1. 实现 `FileConfluenceSource` 读 `confluence/*.md` → 跑通 ingest→map→reduce→load→retrieve→answer。
2. 用 `golden_seed.jsonl` 起步,扩到 ~50 条并冻结 → 跑变体矩阵 → 出 `outputs/eval_report.json` → 看板展示。
3. 如未来需要精确 prompt-hash fixture,再把 MockLLM 的 canned JSON 放进 `llm_canned/`;当前 MockLLM 已在代码里保持确定性。
4. 验收:`uv run python -m backend.pipeline demo` 一键跑通,且在产物里能看到上面这些坑被正确处理(见 `01_CODEX_构建规格.md` §9)。

> 真实数据进内网后,这套假数据仍保留作**回归测试**(对应 `card_ingestion_sop/templates/bad_case_library_纠错案例库.md` 的回归集)。
