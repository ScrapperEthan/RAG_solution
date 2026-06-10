# 分阶段验收闸 + review 清单(防 opencode 再次跑偏)

> **读者**:opencode(执行 + 自检)+ Ethan(G3 人工 + 收 review 包)。
> **为什么有这份**:上次 opencode **一口气从 ingest 跑到 cards**,而病在**第一步 chunk**(整页切成 3 大块),下游全建在坏地基上,直到最后人工 eyeball 才发现。
> **本次规矩 = 一步一闸:每个关键节点产出后,先过该节点的硬验收,过了才做下一步;不过就停下报告,绝不硬着头皮往下盖。**
> 配套:抽取细则 `12`、防碎片化 `13`、总验收 `10`。本文件只管"执行纪律 + 卡点 + 带回什么"。

---

## 0. 元规矩(opencode 必须遵守)

1. **逐节点跑**,不要 `ingest→…→reduce` 一把梭。
2. **每个节点产出后,先自检该节点的"硬验收"**(下面 G0–G4,都是可证伪的)。
3. **任一闸不过 → 立刻停,报告哪条挂了、你怀疑的原因**,**不要**继续往下做。
4. 每个节点**留下证据**(见各闸"交回产物"),最后打包给 Ethan。
5. **G0 和 G3 是硬卡点**:G0 是上次出事的地方、G3 是上次被跳过的人工审 —— 这两处务必停下确认,别自作主张冲过去。

---

## 1. 五道闸

### 🚦 G0 — 切分健全性(`ingest/chunk`)【最关键 · 硬卡点】
> 上次就死在这。**这一闸不过,后面全白做。**

| | |
|---|---|
| 入口前提 | 已按 `12` 实现结构感知切分 |
| **硬验收(全部可证伪)** | **G0.1** chunk 产物里有 `metadata.channel`/`metadata.attribute`,矩阵 section 数 ≈ channels×attributes(**几十个量级**),**不是 3 个 `part 1/2/3`**。<br>**G0.2** 随机抽一个单元格 section(如 channel=whatsApp, attribute=Delivery Mode),其 body **就是那个格子**(≈ `real-time mode only, now only support WPB`),不是整行/整页。<br>**G0.3** access-right Q&A 块里,`UAT`/`PROD` 两个登录 URL 各自落在可定位的 section(切完没被吞)。<br>**G0.4 回归**:纯散文 fixtures 页 chunk 数量/行为**不变**。 |
| **STOP 条件** | G0.1 仍是 3 大块,或单元格没拆开 → **停**,回 `12 §3-A`,**不要跑 map**。 |
| 交回产物 | ① 一个 cell-level section 样例(含 metadata);② chunk 出的 section 总数;③ G0.4 回归一句话。 |

### 🚦 G1 — 抽取 + tier(`map`)
> 让确切值活下来,而不是煮成 narrative。

| | |
|---|---|
| 入口前提 | G0 通过 |
| **硬验收** | **G1.1** 含 URL/email/ticket/数值的 section,`tier=="inline-value"` 且 `fact_value` 是**逐字值**(如 `https://sapp-cmg.hk.hsbc:8004/login`)。<br>**G1.2** 全切片 `inline-value` 计数 **明显 > 0**(这页满是 URL/contact,上次是 **0**,这次必须有不少)。<br>**G1.3** metadata(channel/attribute/row_key)从 chunk **透传**进 map 产物。<br>**G1.4** 概念/职责仍是 `narrative`(别矫枉过正把定义也搬成 inline-value)。 |
| **STOP 条件** | inline-value 计数 = 0,或 UAT URL 不是 inline-value → **停**,回 `12 §3-B`。 |
| 交回产物 | map 里**带 UAT 登录 URL 的那条 inline-value section** 节选 + 全切片 inline-value 计数。 |

### 🚦 G2 — topic 提案 + 防碎片化(`discover`)
| | |
|---|---|
| 入口前提 | G1 通过 |
| **硬验收** | **G2.1** 产出 `proposed_keywords.json`(含 candidates + modules),且**不产 cards**(同 `10` A2)。<br>**G2.2** 每个候选带 `nearest_existing`(D1);若已载入现有词表,带 `dup_warning`(D2,**确定性分**,按 `13 §D2` 公式)。<br>**G2.3** 候选用 `C-PROP-*`,没混进最终 id。<br>**G2.4** 基于**新 chunk** 重新提的 topic —— 别照搬上次那 5 个,数量/命名重新 eyeball。 |
| **STOP 条件** | discover 又开始建卡 / 又造 `C-AUTO-*` → **停**,回 `09`。 |
| 交回产物 | **`proposed_keywords.json` 全文**(给 Ethan 审 + 给 claude 看 D1/D2 有没有正常报)。 |

### 🚦 G3 — 人工冻结(**Ethan 做**,用 `approve.html`)【硬卡点】
> 上次被跳过(opencode 自己冻)。这次必须真人审。

| | |
|---|---|
| 入口前提 | G2 通过,拿到 `proposed_keywords.json` |
| 做什么 | Ethan 打开 `approve.html` → 载入候选 + **现有冻结词表** → 处理 ⚠ 疑似重复(D3 合并/D4 别名回填)→ 真新的才批准 → 导出 `keyword_table.jsonl` → 放到 `paths.keyword_table`。 |
| **硬验收** | 词表每行合法 JSON、`status="approved"`、无重复 id;`load_vocabulary` 能读(同 `10` B2/B3)。 |
| 交回产物 | 冻结后的 **`keyword_table.jsonl`**。 |

### 🚦 G4 — 建卡(`reduce`)
| | |
|---|---|
| 入口前提 | G3 完成,词表就位 |
| **硬验收** | **G4.1** 零 `C-AUTO`;每张卡 `canonical_id` ∈ 冻结词表;**幂等**(连跑两次 cards 哈希一致)。<br>**G4.2** subsection `summary` **不再是占位串**;每个被填充 subsection 至少含 1 条 `inline-value` 或非空 `key_points`。<br>**G4.3**(= `12 §5` T1–T3)卡里能查到 `UAT/PROD 登录 URL`、`whatsApp Delivery Mode`、`Sender ID Maintenance 链接` 作为 **inline-value**。<br>**G4.4** `definition` 不是整页元描述、无拼接病句。 |
| **STOP 条件** | 任一 T 失败 → **停**,定位是 chunk(回 G0)/ map(回 G1)/ builder(回 `12 §3-C`)哪层。 |
| 交回产物 | 完整 **`MDC_Management_Portal.json`** + **channels 卡** + `cards_index.json` + T1–T7 自检结果。 |

---

## 2. 最后拿回来给 claude review 的"对齐包"(Ethan 收齐)

> 等 opencode 跑完(或中途卡在某闸),把下面这些带回来(小文件可直接贴,代码可截图):

1. **opencode 逐闸回报**:G0–G4 每条 pass/fail,失败的写原因(模板见 §3)。
2. **G0**:一个 cell-level section 样例(带 metadata)+ section 总数。
3. **G1**:带 UAT URL 的那条 inline-value section 节选 + inline-value 总计数。
4. **G2**:`proposed_keywords.json` 全文(看 D1/D2 + topic 粒度)。
5. **G3**:冻结后的 `keyword_table.jsonl`。
6. **G4**:完整 `MDC_Management_Portal.json` + channels 卡 + T1–T7 结果。

→ 我会按这 6 样,逐闸跟你对齐:**金子有没有留住、相似度有没有正常报、topic 粒度稳不稳、subsection 是不是真有料**。任一闸有问题,我们就地修,不再让它带病往下盖。

---

## 3. opencode 回报模板(填这个交回)

```
G0 切分    : PASS / FAIL（FAIL 原因：__；section 总数：__）
G1 抽取tier: PASS / FAIL（inline-value 计数：__；UAT URL 是否 inline-value：__）
G2 discover: PASS / FAIL（候选数：__；D1/D2 是否都报：__）
G4 建卡    : PASS / FAIL（零C-AUTO：__；幂等哈希：__；T1–T7：__）
改了哪些文件：__
中途在哪闸停过 / 怎么修的：__
意外发现 / 与 12·13 不符之处：__
```

---

*配套:`12` 抽取细则与 T1–T7、`13` 防碎片化 D1–D4、`10` 总验收清单、`09` 解耦结构。本文件 = 执行纪律(一步一闸)+ review 对齐包。*
