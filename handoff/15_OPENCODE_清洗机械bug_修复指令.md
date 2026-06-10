# 指令(给 opencode):清洗 5 个确定性机械 bug(非 LLM 问题)

> **读者**:opencode(在内网 `rag_solution-kb` 改 + 重跑)。
> **前提**:09/12/13/14 已落地,核心链路(cell 切分 → inline-value → subsection 路由)**已验证正确**(UAT/PROD URL、whatsApp Delivery Mode 都进卡了)。**本指令只修剩下的确定性代码 bug**,不碰已对的部分。改一次,所有页永久生效。
> **说明**:这些 bug 在你内网的代码里,外网仓库没有对应函数。下面给**目标行为 + 参考实现**,你对照自己的实际函数改。改完按 §7 自检。
> **若想要精确到行的 diff**:把下面 5 处涉及的当前函数原文贴回给 Ethan,claude 可写逐行替换。

---

## 0. 一句话

修 5 个 bug:① summary/key_points 硬拼 ② heading 被当 fact ③ 邮箱误解析成 URL / 散文标成 inline-value ④ Step 1–19 漏匹配 ⑤ 旧仓库硬编码 review 项。改完**从 `map` 重跑**,按 T-clean 验收。

---

## 1. B1 — 别再字符串硬拼 summary / key_points(card builder · subsection 填充)

**症状**(实测):
- subsection `Portal links` 的 `summary` = `"Portal links covers … access right application and link: Q: MDC Management Portal access right application and link"`(同句重复 + 回声);
- `key_points` 里 `"PROD Access Right (…): Prod: https://…/login (https://…/login)"`(同一 URL 重复三遍)。

**目标**:
- `summary` **不要把原始 heading/question 拼进去**。只用该 subsection **已抽到的 facts** 生成,或干脆省略该字段。参考:
  ```python
  # 只用结构化 facts，不碰原始 heading/question
  parts = [f"{f['label']}: {f['value']}" for f in facts
           if f.get("value") and f["tier"] != "narrative"]
  summary = "；".join(dict.fromkeys(parts))[:300] or ""   # 去重 + 截断；没有就留空
  ```
- `key_points` **去重**(同一值只留一次)、去掉 `"(URL)"` 这种末尾重复、去掉 `"label: Q: label"` 回声。
- **硬规则:禁止把 heading/question 文本当作 fact 的 value 或拼进 summary。**

## 2. B2 — section 正文等于 heading/question 时,不产 fact(card builder)

**症状**:`{"label":"MDC Management Portal access right application and link","tier":"narrative","value":"MDC Management Portal access right application and link: Q: MDC Management Portal access right application and link"}` —— 这不是事实,是把问题标题回声了一遍。

**目标**:构造一条 fact 前先判断——若该 section 正文**去掉 heading/question 后没有实际内容**(空,或与 heading 本身相等),**跳过,不产这条 fact**。
```python
body = strip_heading(section).strip()
if not body or normalize(body) == normalize(section_heading):
    continue   # 不产 fact
```

## 3. B3 — 邮箱别误解析成 URL;多句散文别标 inline-value(map 抽取)

**症状**:`eric.q.yuan@hsbc.com` 被抽出一条 `value:"http://hsbc.com"` 的 inline-value;另一条把整段 `"an API could be provided … need engage HARO: …"` 标成了 inline-value。

**目标**:
- **邮箱按原样留**(`eric.q.yuan@hsbc.com`),**绝不**从中切出 `http://hsbc.com`。URL 提取的正则别把邮箱域名当 URL。
- `inline-value` 只给**原子精确值**(单个 URL / 邮箱 / 编号 / 数值 / 短码)。**多句散文降级 `narrative`**,或从中抽出原子事实(如联系人 `Eric Q YUAN <eric.q.yuan@hsbc.com>`)。
- 判据:value 含句末标点 / 超过 ~12 词 / 含多个独立事实 → 不是 inline-value。

## 4. B4 — Step 1–19 漏匹配:匹配用 heading_path 包含兜底(reduce 匹配)

**症状**(review_queue 实测):整段 `MDC Project Check List > MDC Engagement and Requirement Process > Step N`(N=1…19)全部 `unmatched-section`,没进 C-0007(`MDC project engagement process`)。

**根因**:section 的 `heading_path` 里**明明有** `MDC Engagement and Requirement Process`,但匹配没用上(只看了 keywords/concepts,或名字与现有 alias 不完全相等)。

**目标(建议两条都做)**:
- **代码兜底**:匹配时,若 section.`heading_path` 任一层(normalize 后)**包含**某 canonical 的 `canonical_name` 或某个 `alias`(子串或词集包含),归到该 canonical。可直接参考外网仓库 `backend/reducer/canonicals.py` 的 `canonical_ids_for`(它本就是用 heading_path 做的)。
- **数据兜底**:给 C-0007 补别名 `"MDC Engagement and Requirement Process"`。
- **验收**:Step 1…N 不再 unmatched,出现在 C-0007 卡(作为 subsections 或按步骤的 facts)。

## 5. B5 — 删旧仓库硬编码 review 项(reducer)

**症状**:review_queue 里 `RQ-0011`(DMP)、`RQ-0019`(OTP)—— 这是外网 fixture 时代 `global_review_items` 里**写死的**,与 MDC 无关。

**目标**:删掉 `global_review_items` 里 DMP / OTP 那两段硬编码(low-confidence 那段保留即可),别再凭空往队列塞与本切片无关的项。

---

## 6. 重跑范围(别整条全跑)

- `chunk`(G0)已过、词表(G3)已冻 —— **不重做**。
- 改完 → **从 `map` 重跑 → `reduce`** → 验收。
- 若 B4 只用"加别名"而不改代码,则**只重跑 `reduce`** 即可。

## 7. 验收(可证伪,基本 grep 就能查)

- [ ] **T-clean1**:全 `outputs/.../cards/*.json` grep **不到** `: Q: ` 回声;summary 无整句重复。
- [ ] **T-clean2**:全 cards / map grep,**没有** value 恰为 `http://hsbc.com` 的 inline-value;邮箱仍以 `eric.q.yuan@hsbc.com` 原样存在。
- [ ] **T-clean3**:`review_queue.jsonl` 里**没有** `Step ` 开头的 unmatched;C-0007 卡里**出现** Step 1…N 的内容。
- [ ] **T-clean4**:`review_queue.jsonl` 里**没有** `RQ-0011` / `RQ-0019`。
- [ ] **T-keep(不许退化)**:UAT=`https://sapp-cmg.hk.hsbc:8004/login`、PROD=`https://pul-mdc-hase.hk.hsbc:8004/login` 仍是 `inline-value`;whatsApp 的 `Delivery Mode / SLO / RTB Cost: real-time mode only, now only support WPB` 仍在渠道卡的 whatsApp subsection。

## 8. 回报

填回:T-clean1–4 + T-keep 各 pass/fail;**每个 bug 实际改在哪个文件/函数**;重跑是从 map 还是只 reduce。

---

*配套:抽取层 `12`、防碎片化 `13`、分阶段闸 `14`。本指令 = 一次性了结 A 类机械噪声;之后扩页靠"代码已修 + 词表冻结 + 抽样/golden 评测",不再逐卡人肉读。*
