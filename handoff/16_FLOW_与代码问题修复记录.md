# 整条 flow + opencode 代码问题与修复记录(canonical)

> **用途**:① 一页看懂当前 canonical 链路每层在做什么;② 记录 opencode 内网代码踩过的坑、以及我们在外网仓库**从零重写的干净版**怎么修的。
> **现状**:`backend/` 的 chunk / map / discover / reduce / canonicals / validation 已是**通用、可测**的 canonical 代码(不是 OCR 转录)。每层都有独立回归测试,**不依赖 yaml/LLM**,内网也能直接 `python -m unittest`。

---

## 1. 整条 flow(逐层)

```
Confluence 页
  │  (复用旧仓库抓页+图)
  ▼
① ingest  →  capture(原页落盘) + chunk(结构感知切分)        backend/ingest/chunk.py
  │   产物: outputs/refs/refs_*.json（cell/record/process/qa/prose section + metadata）
  ▼
② map     →  逐 section 结构化抽取                            backend/mapper/service.py
  │   结构化 section→确定性抽取(tier/fact_value/metadata 透传); 散文→LLM
  │   产物: outputs/map/map_*.json
  ▼
③ discover →  全局提案候选 topic(不建卡)                     backend/reducer/discovery.py
  │   产物: outputs/proposed_keywords.json(+.jsonl/_review.md), 每候选带 D1 nearest_existing + D2 dup_warning
  ▼
〈人工闸〉 →  你用 frontend/approve.html 审/合并/降级 → 冻结    frontend/approve.html
  │   产物: keyword_table.jsonl(approved) → 放到 paths.keyword_table
  ▼
④ refine-boundaries → 合并过的 topic 用 AI 重写 boundary       backend/reducer/boundary.py
  ▼
⑤ reduce  →  match-only 建卡(无 C-AUTO)                       backend/reducer/service.py
      产物: outputs/cards/*.json + inverted_index.jsonl + review_queue.jsonl
  ▼
⑥ load/eval → 入库/检索/三族评测                              backend/load, retrieve, eval
```

**命令**:`ingest → map → discover → 〈approve.html 冻结〉 → refine-boundaries → reduce → load`。

---

## 2. opencode 代码踩过的坑 + canonical 版怎么修

| # | 层 | opencode 的问题 | canonical 版的修法 |
|---|---|---|---|
| 1 | chunk | **过拟合写死**:流程认死标题 `"MDC Engagement…"`;矩阵认 `channel/general information` 白名单;只在首个 `##` 前解析;标签写死 `"Channel Matrix"` | **结构驱动**:流程=标题+编号列表;矩阵=首列短唯一键+≥3列;**全页解析**;标签从真实表头取 |
| 2 | chunk | **流程被拍平成 21 个"Step"**,Jira 链接/锁占位("Authenticate…")变成假 step | **分层解析**:顶层 1./2./3. 才是 step,a/b/c 子项与链接行归属到所属 step;6 步就是 6 步 |
| 3 | map | **page-summary 写死** `"channels, Q&A tables, and engagement process steps"` | 按 section 种类 + 真实实体**通用派生** |
| 4 | map | 邮箱 `eric.q.yuan@hsbc.com` 被误抽成 `http://hsbc.com` 的 inline-value | `should_keep_url` 丢掉与邮箱同域的裸域名;多句散文不标 inline-value |
| 5 | reduce | **写死 flag** `DMP`/`OTP`;subsection 路由有 `portal links`/`contact` MDC 特例 | 去掉写死 flag;subsection **纯按 metadata 路由**(channel/row_key/attribute/question/environment) |
| 6 | reduce | field 用 `"type"` 不符 `validate_card` 的 `"tier"` schema;summary/key_points 拼接 echo("X: Q: X")、subsection 占位 stub、`"-."`/锁占位假事实 | 字段对齐 `tier`;`clean_narrative_text`/`is_junk_value`/`is_heading_only_section` 清洗;summary 从干净 facts 生成 |
| 7 | reduce | **field 爆炸**(definition/overview/details/key_points/examples + 一堆 topic_class 派生) | 收敛到干净核心:definition/overview/config/troubleshoot/pointer/related + subsections |
| 8 | discovery | `propose_from_term` 把渠道/属性名**写死成 canned 返回**(只是 MockLLM 离线兜底) | 通用全局聚类 + 确定性 **D2 dup_warning**(token Jaccard + char-trigram Dice)+ **D1 nearest_existing**,无 canned |
| 9 | 通用 | 内网代码只能拍照→OCR 传出,**OCR 转录有语法+语义错**,不可作 canonical 源 | **从零重写**,OCR 只当"看懂逻辑"的设计参考;每层离线可测 |

> 还有两类**根因级**修复贯穿全程:
> - **解耦**(09):reduce 从"边发现 topic 边建卡"改回"只匹配冻结词表",discover 单独成步、中间加人工冻结闸 → topic 粒度稳定。
> - **抽取层**(12):整页 3 大块 → cell 级切分,确切事实(URL/contact/SLO)以 inline-value 逐字留住,subsection 真填充。

---

## 3. canonical 文件清单 + 测试

| 文件 | 作用 | 测试 |
|---|---|---|
| `backend/ingest/chunk.py` | 结构感知切分 | `tests/test_chunk_general.py`(6) |
| `backend/mapper/service.py` | 结构化确定性抽取 + LLM 散文 | `tests/test_mapper_clean.py`(6) |
| `backend/reducer/discovery.py` | 全局提案 + D1/D2 | `tests/test_discovery_clean.py`(4) |
| `backend/reducer/service.py` | match-only 建卡 + subsection 填充 | `tests/test_reducer_clean.py`(6) |
| `backend/reducer/boundary.py` | 合并后 AI 重写 boundary | (preview 实测) |
| `backend/reducer/canonicals.py` | 词表加载 + heading_path 匹配 | (随 reducer 测) |
| `backend/schemas/validation.py` | card/map/subsection 校验 | (随 reducer 测) |
| `frontend/approve.html` | 人工冻结 + 合并/别名回填(D3/D4) | (preview 实测) |

22 个回归测试全过:`python -m unittest backend.tests.test_chunk_general backend.tests.test_mapper_clean backend.tests.test_reducer_clean backend.tests.test_discovery_clean`。

---

## 4. 重跑提醒

- 这些改了**切分/抽取/建卡**,**必须从 `ingest` 整条重跑**(不是从 discover)。
- 内网换上这套后,预期变化:engagement 流程变 6 个真步骤、各 channel 的确切事实进卡、不再有 echo/stub 垃圾、且**换别的 Confluence 页也成立**(结构驱动)。

## 5. 已知限制 / 待验证

- `reduce` 精简了 opencode 那套**按 topic_class 派生的字段**(workflow→trigger/steps/outputs 等)。若 Business 需要,可在 `reducer/service.py` 的 `build_card` 加回(留了清晰位置)。
- 这套是**离线测过**(22 测试),但**真实产出仍需内网重跑验证**(本机无 yaml/真 LLM)。重跑后按 `handoff/14` 的 G0–G4 闸 + `handoff/12` 的 T1–T7 核对。
- subsection 路由用 `metadata.channel = 行键`(历史命名);如需把 reducer 也改成纯 `row_key`,是个小 follow-up。

---

*配套:解耦 `09`、验收 `10`、抽取层 `12`、防碎片化 `13`、分阶段闸 `14`、清洗 `15`。本文件 = 当前 canonical 链路全景 + 代码问题修复台账。*
