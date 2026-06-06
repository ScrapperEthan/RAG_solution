# 数据摄取 · 卡片构建 SOP(主文档)

> **一句话:** 用 AI 把 Confluence 整理成"卡片",Business 只审不写,审出的每个问题都变成规则喂回系统——让数据摄取成为一套**可复现、能自我进化**的标准流程(SOP)。
>
> **读这份就够入门;细节在 `skills/` 和 `templates/`。** 中文为主,字段/JSON/SQL/prompt 保留英文。

> 📌 **范围更新(重要):** "key topics + keyword list"(以及 `module` 域分区)由**同事的 topic/keyword 组件**产出、Business 审批。**本 SOP 不再自己生成词表**——我们的 `card-reduce` 直接**消费这张审批过的表**作为分组键。我们负责的是:**map 逐页抽取 → reduce 按这张表建卡 → 评测闭环**。两边的接合点 = 那张词表(见 §11 合并)。

---

## 1. 这份 SOP 解决什么问题

我们在做 Confluence 的 RAG / 卡片问答 PoC(背景见上层 `RAG_PoC_Implementation_Spec.md` 和 `Confluence_QA_PoC_方案讨论稿.md`)。原方案前提:**Business 提供"受控关键词表 + 卡片模板"**。

**现实:** 关键词表/主题由**同事的组件**自动生成、Business 审批(我们不重复造);卡片模板我们给默认、Business 微调;Business 整体只**审不写**。

| | 原设想 | 现在的做法 |
|---|---|---|
| 关键词 / topic / module | Business 给 | **同事的组件生成**,Business 审批,**我们消费** |
| 卡片模板 | Business 给 | 用默认模板起步,Business 微调 |
| Business 的角色 | 作者(写) | **审核者(审 + 挑错)** |
| 出错怎么办 | —— | 变成 **bad case → 规则**,系统不再犯 |

> **为什么这样可行:** 人不擅长从零产出,但很擅长**对着具体产物挑错**。把 Business 从"写"降级成"审",既符合他们能给的帮助,又恰好是质量最高的反馈方式。

---

## 2. 名词扫盲(初学者先看这个)

| 术语 | 大白话 | 小例子 |
|---|---|---|
| **map / reduce** | 先逐份做笔记,再按主题汇总 | map 每页一份笔记;reduce 把"讲 DM plugin"的笔记并成一张卡片 |
| **卡片 card** | 一个 topic 的一张"小档案" | "DM Plugin"卡片:定义、配置、关系、坑、每条都带原文出处 |
| **受控词表 / 主题表** | 统一叫法 + 主题清单(**外部输入**,同事产出) | `DM Plugin` ← `Data Management plugin` / `DMP` |
| **module(域)** | 知识的粗粒度分区(外部输入,同事划) | `Integration & API standard` / `Channel standard` … |
| **锚点 anchor** | 指回原文确切位置的指针 | `page_id 123456 > Configuration` |
| **三档 tier** | 一条信息"能不能直接拿来答" | narrative(可总结)/ inline-value(精确值原样搬)/ pointer-only(只有指针) |
| **倒排表** | 关键词 → 出现在哪些页 | `DM Plugin → [页123456, 页777001]` |
| **grounding** | 答题前回原文取证、按原文答并引用 | 不照总结答,顺锚点取原文 |
| **golden set** | 评测题库(冻结) | 30–50 道真实风格的问题 + 标准答案 |
| **bad case** | 一次出错的记录 | "把 DMP 当成新概念了" → 提炼成规则 |
| **回归集** | 改完之后用来验证没改坏的小测试集 | 历史 bad case 的输入,重跑确认修好 |

---

## 3. 整体闭环(SOP 的心脏)

> 关键:**词表/主题/module 是外部输入(同事组件 + Business 审批)。** 我们的环从 map 开始,reduce 按这张审过的表建卡。

```
[外部] 同事组件 → key topics + keyword list + module → Business 审批 ─┐
                                                                       │(作为 reduce 的分组键)
              ┌──────────────── 持续优化的回路 ────────────────┐       │
              │                                                │       ▼
① MCP 抓取(全量切片) ─► ② card-map 逐页抽取(map_*.json) ─► ③ card-reduce 按词表建卡
   │                                                                    │
   │                                  卡片 + 倒排表 + review_queue ◄─────┘
   ▼                                          │
⑥ 质量闸门(golden set,卡片层 > baseline)     ▼
   ▲                                   ④ Business 审卡片/倒排表(精度/召回/裁决)
   │                                          │
   └─────── ⑤ 更新卡片 + 登记 bad case → 提炼规则 → 回写 skill → 加回归集 ──┘
```

**走一遍这个环:**

1. 抓全量切片(别只抓业务点名的页);
2. map 逐页抽取、每页自报原始关键词(`skills/card-map`);
3. reduce 按**同事审批过的词表/主题表**跨页建卡 + 倒排表 + 冲突标注(`skills/card-reduce`);漏网叫法记 review_queue 回报给同事;
4. Business 审卡片/倒排表(精度/召回/裁决,`templates/business_review_checklist`);
5. 据反馈更新卡片 + 登记 bad case → 提炼规则回写 skill → 加回归集(`templates/bad_case_library`);
6. 在 golden set 上验证确实变好,再推进下一个切片。

> 每转一圈,skill 多一条规则、回归集多几条用例——**SOP 就这样越用越准。**

---

## 4. 角色分工

| 角色 | 干什么 | 不干什么 |
|---|---|---|
| **同事的组件** | 产出 key topics + keyword list + module(外部) | —— |
| **你(Ethan)** | 跑 opencode、维护 skill / bad case、把 Business 反馈落地、守闸门、跟同事对接词表 | —— |
| **Business** | **审批 + 挑错**:上游审词表(同事那边),下游审卡片/倒排表(精度/召回)+ 裁决 review_queue | 不从零写关键词/卡片 |
| **opencode** | 执行 **map / reduce** 两个 skill,产出中间产物 | 不替人拍板;不重复造词表 |
| **gpt-5.5** | 抽取、总结、当评测裁判 | 不负责向量检索质量(那是 embedding) |

---

## 5. 中间产物清单

| 产物 | 谁产出 | 长什么样 | 给谁 |
|---|---|---|---|
| `canonical_keywords_受控词表.md`(含 module) | **同事组件(外部)/ Business 审** | 主题 + 规范名 + 别名 + module + 状态 | **reduce 的输入** |
| `outputs/map/map_<page_id>.json` | card-map | 每页一份结构化笔记 + 自报关键词 | reduce + 备查 |
| `outputs/cards/*.json` | card-reduce | 每个 topic 一张卡片(三档字段 + 锚点 + module) | 入库 + Business 抽样 |
| `outputs/inverted_index.jsonl` | card-reduce | keyword→page 倒排表 | **Business 主审材料** |
| `outputs/review_queue.jsonl` | card-reduce | 系统拿不准 / 漏网叫法(回报给同事) | Business / 同事 |
| `bad_case_library_纠错案例库.md` | 你登记 | 错误 + 规则 + 改动记录 | 进化引擎 |

> **"随时与 Business 同步"= 同步这些中间产物**,尤其倒排表和 review_queue,按切片**批量**给(别实时打扰)。

---

## 6. Business 评审协议

详见 `templates/business_review_checklist_评审清单.md`。要点:

- **按切片批量**给三样:倒排表(主审)、review_queue(点名裁决)、卡片抽样。
- Business 只做两个判断:**精度**(关联对不对)、**召回**(有没有漏),外加裁决 review_queue。
- 节奏建议 3 个工作日;表单极简(打勾 + 一句纠正),成本压到 20–30 分钟/切片。
- 注:**key topics / keyword list 的审批是上游**(同事的组件 + Business),本清单只审卡片/倒排表。

---

## 7. Bad case 机制(SOP 为什么能"不断优化")

详见 `templates/bad_case_library_纠错案例库.md`。三条铁律:

1. **每个分歧/错误都登记**,不靠记忆。
2. **优先提炼"规则",不堆"例子"**:能一句规则覆盖的写成规则;规则讲不清才放少量 few-shot。**否则 skill 的 prompt 会越来越长、还会过拟合。**
3. **改完进回归集、重跑验证**:回归集(测 skill 行为)和 golden set(测最终效果)**两者都要,别混**。

---

## 8. 质量闸门(别让 SOP 变成自嗨)

**卡片做得 Business 满意 ≠ 检索/答题真的变好。** 卡片是手段,不是目的。挂到评测(细节见 `RAG_PoC_Implementation_Spec.md` §11 与讨论稿 §8):

- 所有改动都在**冻结的 golden set** 上跑,apples-to-apples。
- 两个关键指标:**`association recall`**(该进卡片的页关联上了多少)、**`漏钻率`**(精确题本该回原文却用卡片直答的比例)。
- **闸门规则:卡片层只有跑赢 baseline(纯 RAG)才采纳**;否则回 bad case 找因。
- ⚠️ 评测题**必须与生成卡片的 prompt 解耦**,否则 recall 虚高(spec §11.1 红线)。

---

## 9. 落地顺序(先窄后宽)

1. **先一个切片**:`06-Delivery / 10. Planned Project / 2026 Planned Project`(先跟同事确认这块的词表/主题已审)。
2. 把**闭环跑通一遍**:map → reduce(用词表)→ Business 审卡 → bad case → 回写 skill → 重跑。
3. 在 golden set 上证明**卡片层 > baseline**,过闸门。
4. **再扩**下一个切片。
5. **增量幂等**:页 `version` 变 → 只重跑该页 map → 只对受影响概念 reduce(讨论稿 §5.5)。

---

## 10. 文件清单与关系

```
card_ingestion_sop/
├── README_数据摄取卡片SOP.md         ← 你在这(入口/总览)
├── skills/
│   ├── card-map/SKILL.md             ← 逐页抽取 + 自报关键词
│   └── card-reduce/SKILL.md          ← 按(外部)词表建卡 / 冲突标注
└── templates/
    ├── canonical_keywords_受控词表.md      ← 词表/主题表(★外部输入:同事组件产出,本仓库放一份对接副本)
    ├── bad_case_library_纠错案例库.md      ← 进化引擎(错误→规则)
    └── business_review_checklist_评审清单.md ← 给 Business 的审核表(审卡片/倒排表)

上层既有文档:
├── RAG_PoC_Implementation_Spec.md     ← 检索/切块/字段/评测的实现 spec
└── Confluence_QA_PoC_方案讨论稿.md     ← 三方案与卡片三档结构的讨论稿
```

---

## 11. 与同事工作的合并(接合点 = 词表)

- **接合契约**:同事组件产出的"主题/关键词/module 表" = 我们 `card-reduce` 的输入(受控词表)。双方先对齐这张表的**列与文件格式**(见 `templates/canonical_keywords_受控词表.md` 的字段;module 作为一列)。
- **流向**:同事组件 → 审批后的表 →(放到约定路径)→ 我们的 map/reduce 消费 → 卡片/倒排表 → Business 审 → 反馈(漏网/歧义)回报给同事更新表。
- **module 的用法**:作为**元数据 facet**(过滤/导航),**不做删页过滤**——详见与本 README 同批交付的合并说明。

---

*本 SOP 是活文档:skill 会加规则、案例库会积累。每个切片收尾回看一次,合并规则、清理 few-shot、整体跑回归集。*
