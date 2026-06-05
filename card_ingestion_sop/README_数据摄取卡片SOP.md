# 数据摄取 · 卡片构建 SOP(主文档)

> **一句话:** 用 AI 把 Confluence 自动整理成"关键词 + 卡片",Business 只审不写,审出的每个问题都变成规则喂回系统——让数据摄取成为一套**可复现、能自我进化**的标准流程(SOP)。
>
> **读这份就够入门;细节在 `skills/` 和 `templates/`。** 中文为主,字段/JSON/SQL/prompt 保留英文。

---

## 1. 这份 SOP 解决什么问题

我们在做 Confluence 的 RAG / 卡片问答 PoC(背景见同目录上层的 `RAG_PoC_Implementation_Spec.md` 和 `Confluence_QA_PoC_方案讨论稿.md`)。原方案里有个前提:**Business 提供"受控关键词表 + 卡片模板"**。

**现实变了:Business 帮不上太多忙,关键词和模板得我们自己搞。** 于是把思路反过来:

| | 原设想 | 本 SOP 的做法 |
|---|---|---|
| 关键词 / topic | Business 给 | **AI 自底向上长出来**,Business 审批 |
| 卡片模板 | Business 给 | 用默认模板起步,Business 微调 |
| Business 的角色 | 作者(写) | **审核者(审 + 挑错)** |
| 出错怎么办 | —— | 变成 **bad case → 规则**,系统不再犯 |

> **为什么这样可行:** 人不擅长从零产出,但很擅长**对着具体产物挑错**。把 Business 从"写"降级成"审",既符合他们能给的帮助,又恰好是质量最高的反馈方式。这跟 PoC 里 golden set "人只抽检、不从零编"是同一个道理。

---

## 2. 名词扫盲(初学者先看这个)

| 术语 | 大白话 | 小例子 |
|---|---|---|
| **map / reduce** | 先逐份做笔记,再按主题汇总 | map 每页一份笔记;reduce 把"讲 DM plugin"的笔记并成一张卡片 |
| **卡片 card** | 一个 topic 的一张"小档案" | "DM Plugin"卡片:定义、配置、关系、坑、每条都带原文出处 |
| **关键词 / topic** | 卡片的名字与合并键 | `DM Plugin` |
| **受控词表** | 统一叫法的总表(规范名 + 别名) | `DM Plugin` ← `Data Management plugin` / `DMP` |
| **锚点 anchor** | 指回原文确切位置的指针 | `page_id 123456 > Configuration` |
| **三档 tier** | 一条信息"能不能直接拿来答" | narrative(可总结)/ inline-value(精确值原样搬)/ pointer-only(只有指针) |
| **倒排表** | 关键词 → 出现在哪些页 | `DM Plugin → [页123456, 页777001]` |
| **grounding** | 答题前回原文取证、按原文答并引用 | 不照总结答,顺锚点取原文 |
| **golden set** | 评测题库(冻结) | 30–50 道真实风格的问题 + 标准答案 |
| **bad case** | 一次出错的记录 | "把 DMP 当成新概念了" → 提炼成规则 |
| **回归集** | 改完之后用来验证没改坏的小测试集 | 历史 bad case 的输入,重跑确认修好 |

---

## 3. 整体闭环(SOP 的心脏)

```
        ┌─────────────────────────── 持续优化的回路 ───────────────────────────┐
        │                                                                        │
  ① MCP 抓取        ② card-map          ③ card-reduce            ④ 中间产物        │
  Confluence 页 ──►  逐页抽取     ──►   跨页合并/归一化   ──►   卡片 + 倒排表        │
  (全量切片)        map_*.json         冲突取新+标注          + review_queue        │
                                                                   │              │
                                                                   ▼              │
                                                          ⑤ Business 评审          │
                                                       (审清单:精度/召回/裁决)      │
                                                                   │              │
                                  ┌────────────────────────────────┤              │
                                  ▼                                 ▼              │
                          ⑥ 更新词表/卡片                   ⑦ 登记 bad case          │
                          (approved/改值)                  → 提炼"规则"             │
                                                            → 回写 skill ───────────┘
                                                            → 加入回归集
                                                                   │
                                                                   ▼
                                  ⑧ 质量闸门:在冻结 golden set 上跑,
                                     卡片层跑赢 baseline 才采纳 → 再扩下一个切片
```

**走一遍这个环,就理解了整套 SOP:**
1. 抓全量切片(别只抓业务点名的页);
2. map 逐页抽取(`skills/card-map`);
3. reduce 跨页合并 + 归一化 + 冲突标注(`skills/card-reduce`);
4. 产出卡片、倒排表、review_queue;
5. Business 按清单审(`templates/business_review_checklist`);
6. 你据反馈更新词表/卡片;
7. 同时把错登记成 bad case,提炼成规则回写 skill,加进回归集(`templates/bad_case_library`);
8. 在 golden set 上验证确实变好,再推进下一个切片。

> 每转一圈,skill 多一条规则、词表多几个 approved、回归集多几条用例——**SOP 就这样越用越准。**

---

## 4. 角色分工

| 角色 | 干什么 | 不干什么 |
|---|---|---|
| **你(Ethan)** | 跑 opencode、维护 skill / 词表 / bad case、把 Business 反馈落地、守质量闸门 | —— |
| **Business** | **只审批 + 挑错**:精度(关联对不对)、召回(漏没漏)、裁决 review_queue | 不从零写关键词/卡片 |
| **opencode** | 执行 map / reduce 两个 skill,产出中间产物 | 不替人拍板(拿不准就进 queue) |
| **gpt-5.5** | 抽取、归一化、总结、当评测裁判 | 不负责向量检索质量(那是 embedding) |

---

## 5. 中间产物清单(都是"给人看 + 给机器用"两用)

| 产物 | 谁产出 | 长什么样 | 给谁 |
|---|---|---|---|
| `outputs/map/map_<page_id>.json` | card-map | 每页一份结构化笔记(§schema 见 map skill) | reduce + 备查 |
| `outputs/cards/*.json` | card-reduce | 每个 topic 一张卡片(三档字段 + 锚点) | 入库 + Business 抽样 |
| `outputs/inverted_index.jsonl` | card-reduce | keyword→page 倒排表 | **Business 主审材料** |
| `outputs/review_queue.jsonl` | card-reduce | 系统拿不准、点名要人裁决的 | **Business 必看** |
| `canonical_keywords_受控词表.md` | reduce 写 / Business 审 | 规范名+别名+状态 | 全流程共享 |
| `bad_case_library_纠错案例库.md` | 你登记 | 错误 + 规则 + 改动记录 | 进化引擎 |

> **"随时与 Business 同步"= 同步这些中间产物**,尤其倒排表和 review_queue。但**别真的实时打扰**——按切片**批量**给(见评审节奏),否则同步会变负担、最后不了了之。

---

## 6. Business 评审协议(怎么同步才不流于形式)

详见 `templates/business_review_checklist_评审清单.md`。要点:

- **批量、按切片**给三样:倒排表(主审)、review_queue(点名裁决)、卡片抽样。
- Business 只做两个判断:**精度**(关联对不对)、**召回**(有没有漏),外加裁决 review_queue。
- 给个**节奏**(建议 3 个工作日反馈)和**极简表单**(打勾 + 一句纠正),把他们的成本压到 20–30 分钟/切片。
- 他们指出的"漏页",正好是评测里 `association recall` 的真值来源。

---

## 7. Bad case 机制(SOP 为什么能"不断优化")

详见 `templates/bad_case_library_纠错案例库.md`。三条铁律:

1. **每个分歧/错误都登记**,不靠记忆。
2. **优先提炼"规则",不堆"例子"**:能一句规则覆盖的写成规则(回写 skill 的规则区);规则讲不清才放少量 few-shot。**否则 skill 的 prompt 会越来越长、还会过拟合到见过的个案。**
3. **改完进回归集、重跑验证**:确认这条修好了、且没碰坏别的。回归集(测 skill 行为)和 golden set(测最终效果)**两者都要,别混**。

> 这就是把"踩坑"变成"资产"的机制:坑踩一次,规则记一条,下次自动绕开。

---

## 8. 质量闸门(别让 SOP 变成自嗨)

**卡片做得 Business 满意 ≠ 检索/答题真的变好。** 卡片是手段,不是目的。所以必须挂到评测(评测细节见 `RAG_PoC_Implementation_Spec.md` §11 与讨论稿 §8):

- 所有改动都在**冻结的 golden set** 上跑,**apples-to-apples** 比较。
- 关键两个指标(讨论稿 §8.2):
  - **`association recall`**:该进某卡片的页,倒排表实际关联上了多少 → 直接量化"补回漏页"是否有效。
  - **`漏钻率`**:精确题里 agent 本该回原文取证却直接拿卡片作答的比例 → 卡片方案的头号风险。
- **闸门规则:卡片层只有在 golden set 上跑赢 baseline(纯 RAG)才采纳**;否则回到 bad case 找原因,而不是继续堆卡片。
- ⚠️ 评测题**必须与生成索引/卡片的 prompt 解耦**,否则 recall 虚高(spec §11.1 红线)。

---

## 9. 落地顺序(先窄后宽)

1. **先只做一个切片**:`06-Delivery / 10. Planned Project / 2026 Planned Project`。
2. 把**闭环跑通一遍**:map → reduce → Business 评审 → bad case → 更新 skill → 重跑。先求"环转起来",再求"卡片完美"。
3. 在 golden set 上证明**卡片层 > baseline**,过闸门。
4. **再扩**下一个切片。每扩一次,skill/词表/回归集都更成熟。
5. **增量与幂等**:页 `confluence_version` 变 → 只重跑该页 map → 只对受影响概念重做 reduce(讨论稿 §5.5)。别每次全量重算。

> **别一上来就想写出完美的 skill。** 让前几个 bad case 来塑造它——这正是 SOP 的设计意图。

---

## 10. 文件清单与关系

```
card_ingestion_sop/
├── README_数据摄取卡片SOP.md         ← 你在这(入口/总览)
├── skills/
│   ├── card-map/SKILL.md             ← 逐页抽取(给 opencode)
│   └── card-reduce/SKILL.md          ← 跨页合并/归一化(给 opencode)
└── templates/
    ├── canonical_keywords_受控词表.md      ← 关键词总表(产物,会长大)
    ├── bad_case_library_纠错案例库.md      ← 进化引擎(错误→规则)
    └── business_review_checklist_评审清单.md ← 给 Business 的审核表

上层既有文档(本 SOP 与之对齐,不重复):
├── RAG_PoC_Implementation_Spec.md     ← 检索/切块/字段/评测的实现 spec
└── Confluence_QA_PoC_方案讨论稿.md     ← 三方案与卡片三档结构的讨论稿
```

**怎么开始用:**
1. 读完本 README;
2. 把 `skills/` 两个 SKILL.md 放到内网 opencode 能读到的位置;
3. 先对 2026 Planned Project 切片跑 map → reduce;
4. 拿 `templates/business_review_checklist` 找 Business 审第一批倒排表;
5. 反馈回来 → 更新词表 + 登记 bad case + 回写 skill → 重跑;
6. 过 golden set 闸门 → 扩下一个切片。

---

*本 SOP 是活文档:词表会长大、skill 会加规则、案例库会积累。每个切片收尾时回看一次,合并规则、清理 few-shot、整体跑回归集。*
