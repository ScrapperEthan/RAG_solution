# 卡片(card)字段说明 + 待与 Business 核对清单

> **这份文档干两件事:**
> 1. **字典**:把 `outputs/cards/*.json` 里**每个字段**讲清楚——是什么、举例、从哪来、必不必填。先帮你(和 Business)看懂现在长什么样。
> 2. **决策表**:列出**可以加但还没加**的候选字段,每个都带"加它解决什么 / 成本 / 我的建议",做成可勾选的表,直接拿去和 Business 过一遍"要不要加"。
>
> **语言约定**(沿用全仓库):中文讲解,字段名 / JSON / 取值保留英文。
> **上游依据**:`Confluence_QA_PoC_方案讨论稿.md` §5–§6、`card_ingestion_sop/skills/card-reduce/SKILL.md` §3–§4、`handoff/05_合并对接_module_facet.md`、`RAG_PoC_Implementation_Spec.md` §6–§7。

---

## 0. 先看这条:现在审的是"结构",不是"内容"

`outputs/cards/*.json` 这 8 张卡片是**从离线 fixtures(合成测试数据)跑出来的**。所以你会看到 `definition` 的值长这样:

> `"DM Plugin: What is the DM Plugin 说明 DM Plugin, Journey Plugin 的 what-is 信息(narrative)。"`

——这是**占位文本,不是真实摘要**。和 Business 这一轮要核对的是**字段设计(schema):该有哪些字段、每个字段什么含义、要不要增减**;**不是**这几句话写得好不好。等接上真实 Confluence + 同事的词表,内容质量再单独评(走 `business_review_checklist`)。

---

## 1. 一张卡片的整体长相

一张卡片 = **顶层身份信息** + 一个 `fields[]` 数组(真正的知识条目,每条带三档 tier 和原文锚点) + `flags[]`(给人看的提示)。

```jsonc
{
  // ── 顶层:这张卡片"是谁" ──
  "canonical_id": "C-0007",                 // 稳定主键
  "canonical_name": "DM Plugin",            // 规范名
  "aliases": ["DM plugin", "DMP", ...],     // 别名/缩写/拼写变体
  "module": ["Integration & API standard",  // 域标签(多标签 facet)
             "Delivery & tracking standard"],
  "boundary": "消息投递…;不含 Journey 编排或 Adaptor 转换。", // 范围边界
  "topic_type": "component",                // 分类提示(不参与分组)
  "status": "approved",                     // proposed → approved

  // ── 主体:一条条知识,每条自带"能不能直接拿来答" ──
  "fields": [
    {
      "field": "config",                    // 这条信息是什么(字段名)
      "tier": "inline-value",               // 三档:能不能直接答
      "value": "batch_size: 1000; max_retry: 3",
      "authoritative": true,                // 冲突时这条是"取新"胜出值
      "conflict": true,                     // 多页/多版本不一致
      "conflict_detail": [ ... ],           // 各来源各值,摆出来不藏
      "sources": [ {page_id, anchor, source_url, confluence_version} ]
    },
    { "field": "pointer", "tier": "pointer-only", "value": null,
      "pointer_to": "Journey Plugin page > Integration", "sources": [ ... ] },
    { "field": "related_components", "tier": "narrative",
      "value": "...", "soft_links": ["C-0008","C-0009"], "sources": [ ... ] }
  ],

  // ── 提示:需要人留意的点 ──
  "flags": ["alias 'DMP' should remain auditable in Business review",
            "config field has version/update conflict"]
}
```

---

## 2. 顶层字段字典(逐个讲)

| 字段 | 含义(大白话) | 例子 | 谁产出 / 从哪来 | 必填 |
|---|---|---|---|---|
| `canonical_id` | 这张卡片的**身份证号**,稳定、永不复用/改。换名字也认得出是同一个。 | `C-0007` | 导入词表时分配 | ✅ |
| `canonical_name` | **规范名**(对外统一叫法)。卡片合并、倒排表分组都以它为键。 | `DM Plugin` | 同事词表 `topic` 列 | ✅ |
| `aliases` | **别名/缩写/拼写变体**。原文里出现 `DMP`/`Data Management plugin` 都靠它认回 `DM Plugin`。**归类成败的关键**——别名缺了,召回直接掉。 | `["DM plugin","DMP"]` | 同事词表 `aliases` 列(★见 §6 缺口) | ✅ |
| `module` | **域标签**,粗粒度分区,**多标签**(一张卡可属多个)。取值来自同事的 6 个 module。用途:检索预过滤、看板按域拆、新人按域学。**只打标签,绝不用来删页。** | `["Integration & API standard","Delivery & tracking standard"]` | 同事词表 `module` 列 | ✅(可为多个) |
| `boundary` | **范围边界**:这个 topic 管到哪、不管哪。**喂给归类判断**,帮系统判断某段原文属不属于该 topic,专治 `OTP` 这种一词多义的误归。 | `"消息投递…;不含 Journey 编排或 Adaptor 转换。"` | 同事词表 `topic boundary` 列 | 建议必填 |
| `topic_type` | **分类提示**(这是组件?流程?计划?),**只做提示,不参与分组**。 | `component` / `process` / `service` / `initiative` / `planning` / `inventory` | 同事词表 `type` 列原样留 | 可选 |
| `status` | **审批状态**:`proposed`(系统提的,待审)→ `approved`(Business 审过)。只有 approved 的概念才进正式流程。 | `approved` | Business 审批后改 | ✅ |
| `fields` | **主体**:一个数组,装这张卡片的所有知识条目。每条结构见 §3。 | (见下) | card-reduce 生成 | ✅ |
| `flags` | **给人看的提示**:这张卡片有哪些地方要留意(冲突、缩写待确认…)。 | `["config field has version/update conflict"]` | card-reduce 生成 | 可空 `[]` |

---

## 3. `fields[]` 里每一条的字段字典

`fields` 数组里的**每一条**代表"这个 topic 的某一类信息"(定义、配置、排障、关系…)。结构如下:

| 字段 | 含义 | 例子 | 何时出现 |
|---|---|---|---|
| `field` | **这条信息是什么类别**(字段名)。当前实际出现的有:`definition` / `config` / `troubleshoot` / `related_components` / `pointer` / `config_pointer` / `troubleshoot_notes`。 | `config` | 每条必填 |
| `tier` | **三档**:这条信息"能不能直接拿来答"。核心机制,见 §4。 | `inline-value` | 每条必填 |
| `value` | 这条信息的**实际内容**。`pointer-only` 档时为 `null`(卡片不存值,只给位置)。 | `"batch_size: 1000; max_retry: 3"` | narrative / inline-value 有;pointer-only 为 null |
| `sources` | **原文出处数组**,每个出处含 `page_id` / `anchor`(原文确切位置) / `source_url` / `confluence_version`。**每条 claim 都要能点回原文**,否则下游无法 grounding(回原文取证)。 | `[{page_id:"777001", anchor:"SFMC Migration > DM Plugin Config", ...}]` | 每条必填 |
| `pointer_to` | 仅 `pointer-only` 档:**该去哪看**(卡片不放值,只给指针)。 | `"DM Plugin Overview > Configuration"` | 仅 pointer-only |
| `authoritative` | 仅精确值:多版本冲突时,这条是不是**"取新"胜出**的那个值。 | `true` | 冲突相关时 |
| `conflict` | 这条信息在多页/多版本间**是否不一致**。 | `true` | 精确字段可能有 |
| `conflict_detail` | 冲突时**把各来源各值全摆出来**(value/page_id/confluence_version/update_at),不让系统偷偷挑一个。 | `[{value:"batch_size:500",page_id:"123456",...},{value:"batch_size:1000",...}]` | 仅 `conflict=true` |
| `soft_links` | 关系字段用:指向相关卡片的 `canonical_id` 列表(**软链接**,PoC 阶段不做全量实体归并)。 | `["C-0008","C-0009","C-0100"]` | 多见于 `related_components` |

---

## 4. ⭐ 三档 tier —— 整套设计的"心脏"(务必给 Business 讲清这个)

每条信息都标一个 tier,决定答题 agent **能不能张口就答、还是必须回原文翻一遍**:

| 档位 tier | 什么意思 | 例子 | agent 能否直接答 |
|---|---|---|---|
| `narrative` | 叙述性(定义/职责/关系),**可由 LLM 总结合并** | "DM plugin 负责把消息投递到各渠道…" | ✅ 概念类直接答 |
| `inline-value` | **精确值原样从原文搬来**,带锚点 | `max_retry: 3` 来源 `PageB#Config` | ✅ 且自带出处(≈ 已取证) |
| `pointer-only` | 卡片**不放值、只给位置** | "重试配置见 `PageB#Configuration`" | ❌ 必须下钻取原文 |

**为什么这么设计(一句话价值):** 它把 agent 的判断从"我这总结**够不够好**"(主观、不可靠)变成"卡片这字段**有值还是只有指针**"(客观、可靠)。配置/错误码这种精确信息**绝不做"总结的总结"**——要么逐字搬(`inline-value`),要么干脆只留指针(`pointer-only`),**绝不编一个像样的值**。这是精确题不答错的根本保障。

---

## 5. 现状评估:哪些设计是**合理**的(可以放心给 Business 背书)

| # | 设计点 | 为什么合理 |
|---|---|---|
| 1 | **三档 tier** | 让"能否直接答"变成客观判断,精确题靠 grounding 兜底。这是全方案最有价值的一处设计。 |
| 2 | **每条 claim 带 `sources` 锚点** | 答案可回原文、可引用,满足"引出原文"的硬目标。 |
| 3 | **冲突显式标注**(`conflict` + `conflict_detail` + `authoritative`) | 取新的同时把分歧摆出来交人裁决,不静默选值——技术文档最容易出错的地方被堵住。 |
| 4 | **`module` 多标签 + 绝不删页** | 既能按域过滤/导航,又不牺牲长尾召回(低价值页仍可被 RAG 检索到)。 |
| 5 | **`boundary` 喂归类** | 用一句范围描述压住 `OTP` 式一词多义误归,成本极低、收益直接。 |
| 6 | **`soft_links` 软链接做关系** | 规避了"自动实体归并"这个最难的环节,适合 PoC 阶段。 |
| 7 | **`status` + `flags`** | 人在环路里(human-in-the-loop)的治理钩子,Business 审得动。 |

**结论:核心 schema 是站得住的,不需要推倒重来。** 下面是一些"小问题"和"可加项",属于打磨,不是返工。

---

## 6. ⚠️ 现状里需要修的小问题(不涉及"加字段",但建议一起跟 Business / 同事对齐)

| # | 问题 | 现状 | 建议 |
|---|---|---|---|
| P1 | **文档与产出不同步** | `card-reduce/SKILL.md` §3.2 和 `spec` §7 还写的是旧字段 `component`(单值);实际卡片已用 `module`(数组)+ 新增 `boundary` / `topic_type`。 | 把 SKILL.md / spec 的 schema 更新成实际形态(以 `handoff/05` 为准)。 |
| P2 | **`fields[].field` 命名不统一** | 实际出现 `pointer` / `config_pointer` / `troubleshoot_notes`,而模板 §4 里的 `responsibility` / `interface_deps` / `catch_all` **一次都没产出**。 | 定一个**受控字段名清单**(见 §7-C),对齐模板与产出。 |
| P3 | **同名字段 tier 不一致** | `troubleshoot` 在 `DM_Plugin` 是 `inline-value`,在 `MDC_OTP_Service` 却是 `narrative`。 | 可能合理(原文本身一个有值一个只有叙述),但要确认是**有意**而非抽取漂移。 |
| P4 | **`topic_type` 无受控词表** | 8 张卡出现 6 种自由值(component/process/service/initiative/planning/inventory)。 | 和同事/Business 对齐一个**小受控词表**,否则后续按 type 统计/过滤会碎。 |

---

## 7. 🗳️ 待与 Business 核对:**要不要加这些字段?**(决策表)

> 用法:和 Business 逐行过。"我的建议"是默认值;最后一列空着给 Business 拍板。
> 三类:**A=卡片顶层候选**、**B=词表已有但没落到卡片上**、**C=字段命名/模板治理**。

### A. 卡片顶层 —— 可新增的字段

| 候选字段 | 是什么 | 加它解决什么问题 | 成本 | 我的建议 | Business 决定 |
|---|---|---|---|---|---|
| `owner` / `steward` | 这个 topic **谁负责 / 找谁问** | 答案旁可附"归属人";审核可路由到对的人。Confluence 页本来就有 `owner`,可继承,几乎白捡。 | 低 | **建议加**(继承页 owner) | ☐ 加 ☐ 不加 |
| `last_reviewed` / `as_of` + `source_checked` | 卡片**最后一次被核/生成的时间**;高风险精确值是否回源核过 | 卡片里的 `inline-value` 本质是**缓存,会过期**(讨论稿 §6.5)。现在只有逐源的 `confluence_version`,没有卡片级"新鲜度"。 | 中 | **建议加轻量版**(至少加 `generated_at`;高风险值加"回源已核"标记) | ☐ 加 ☐ 不加 |
| `confidence` | 这张卡/这条字段的**置信度** | 同事词表里**本来就有**,透传上来可帮 Business **排审核优先级**(先看低分的)。 | 低 | **建议加**(透传) | ☐ 加 ☐ 不加 |
| `note_useful` | "这个 topic **为什么重要**"一句话 | 给人读的 wiki 副产品;同事词表已有,透传即可。 | 低 | 可选(想要"可读知识库"就加) | ☐ 加 ☐ 不加 |
| `related_pages`(真值) | 同事标注的"该 topic 关联哪些页" | 当 `association_recall` 的**独立真值**校我们的倒排表。**通常留在词表/评测侧即可,不必塞进卡片**。 | 低 | **暂不加到卡片**(评测侧用) | ☐ 加 ☐ 不加 |
| `card_worthy` / `priority` | 标记"低价值"内容 | 这是 **section/page 级**的"不删页"标记;**卡片只在高价值 topic 上才建**,所以卡片级一般 **N/A**。 | — | **不加**(层级不对) | ☐ 加 ☐ 不加 |

### B. 同事词表里**已有**、但当前**没落到卡片**上的字段(确认要不要透传)

| 词表字段 | 现在去哪了 | 要不要也放卡片上? | 我的建议 |
|---|---|---|---|
| `confidence` | 进 `inverted_index` / `review_queue` | 见 A | 透传到卡片 |
| `note_useful`(why useful) | 仅词表 | 见 A | 可选透传 |
| `review_note` | 仅词表 / review_queue | 卡片一般不需要 | 不透传 |
| `related_pages` | 评测真值 | 见 A | 留评测侧 |

### C. 字段命名 / 模板治理(不是"加字段",是"定规矩")

| 项 | 现状 | 建议(待 Business/同事确认) |
|---|---|---|
| `fields[].field` 受控清单 | 自由命名,有 `pointer` / `config_pointer` / `troubleshoot_notes` 等 | 定一套**受控字段名**,建议对齐 spec §6.3 的 `content_type` 词表:`what-is / how-to / config / troubleshoot / reference / decision / meeting-notes`,外加 `definition` / `related_components` / `pointer`。 |
| 模板里没用上的字段 | `responsibility` / `interface_deps` / `catch_all` 模板有、产出无 | 确认:**保留**(以后会用)还是**从模板删掉**(避免误导)。 |
| 多套模板 | 现在一套通用 | 是否按 `content_type` 设多套模板?(spec §14 / 讨论稿 §9 的待定项) |

---

## 8. 给 Business 的一句话开场(可直接念)

> "卡片的**核心结构**(三档可信度 + 原文锚点 + 冲突标注)我们觉得是对的,想请你确认两件事:
> ① 这几个**可加字段**——`owner`(谁负责)、`新鲜度/回源核对`、`confidence`(置信度)——要不要加进卡片;
> ② `topic_type` 和字段名要不要**定一套受控词表**。
> 其余只是文档同步的小修,不影响你判断。"

---

*附:本文档对应的代码改造点见 `handoff/05_合并对接_module_facet.md` §3;Business 逐切片的精度/召回审核流程见 `card_ingestion_sop/templates/business_review_checklist_评审清单.md`(与本文档分工:那份审"关联对不对",本文档审"字段设计本身")。*
