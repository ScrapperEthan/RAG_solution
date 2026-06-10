# 新页 onboarding 与合并模型(防止 topic 碎片化)

> **用途**:当**新的 Confluence 页**进来时,如何把它的内容加进知识库——要么并进已有 topic,要么新增 topic——**且不产生"同一个东西两张卡"的碎片化**。
> **读者**:Ethan(操作模型)+ opencode(§4 要实现的部分)。
> 承接:`09`(解耦)、`12`(抽取层)。

---

## 1. 两条路(先建立心智模型)

新页 `ingest → map` 后,它的 section 在 reduce 时只有两种去向:

**路 A — 讲的是已有 topic → 自动合并(无需建新卡)。**
reduce 把**所有页**的 section 按 `canonical_id` 跨页分组,一组建一张卡。所以新页里匹配上某 topic 的 section,会自动并进那张已有卡(加 sources / subsection / 事实);精确值跨页不一致 → 取新 + `conflict_detail` 标注。**靠词表里的 `aliases` / `boundary` 把新页的不同叫法认回老 topic。**

**路 B — 讲的是新 topic(词表里没有)→ 不自动建卡。**
匹配不上的 section 进 `review_queue`。要加就:**重跑 `discover`(只提净增)→ approve.html 批准新行 → reduce 出新卡**。新 topic 拿新的稳定 `canonical_id`,不撞老的。

> **增量纪律**:词表**只增不改老行**(老 topic 的 id/名字冻住 → 幂等);新一批 discover 只提净增;12 的 chunk/map 改进对每张新页自动生效。

---

## 2. ⚠️ 核心风险:碎片化(同一个东西,被当成两个)

**这是新页 onboarding 最危险的失败模式,也是必须重点防的:**

> 新页讲的明明是已有的 `MDC Management Portal`,但 AI 给候选起名叫 `MDC Portal` / `Management Portal access`,名字略不同 → 走了路 B → 拿了**新的 canonical_id** → **没合并成功 → 出现两张讲同一个东西的卡**。

为什么光靠现有设计挡不住:
- discover **确实**会拿到现有 approved 词表、被要求"先映射到已有"——但这依赖 **AI 判断**,表面形差一点、boundary 写得糊,它就可能判成"新的";
- **人工 review 也不可靠**:词表长到几十上百个,审的人**记不全**历史 topic,near-duplicate 一样会漏过去。

**所以不能把"认回老 topic"交给 AI 判断 + 人脑记忆。要做成显式、确定性、可学习的机制 —— 下面四道防线。**

---

## 3. 四道防线(让"认回老 topic"可靠)

### D1 — discover 必须对每个候选**显式报告"最像哪个已有 topic"**
discover 输入已含完整 approved 词表(名/别名/boundary)。强化输出:**即使它认为某候选是"新的",也必须给出 `nearest_existing`**:
```json
{ "canonical_name": "MDC Portal access",
  "nearest_existing": {"canonical_id": "C-0002", "name": "MDC Management Portal",
                       "similarity": 0.82, "reason": "都讲 portal 访问入口与 access right"},
  "status": "proposed" }
```
→ 把"疑似重复"**变可见**,而不是让 AI 静默拍板建新。`similarity` 高于阈值(如 ≥0.6)的,在 review 表里标 ⚠️。

### D2 — 确定性 fuzzy 去重预检(非 AI 兜底)
discover 写 `proposed_keywords.json` 前,跑一道**纯字符串**比对:每个候选的 `name + aliases + evidence_keywords` vs 现有词表的 `name + aliases`,算 token 重叠 / 编辑距离;高分对写进 `dup_warning`。
- 专治表面变体:`Notification Preference` vs `Notification Preferences`、`MDC Portal` vs `MDC Management Portal`、大小写/连字符/单复数差异。
- 这是 AI 漏报时的**确定性兜底**,不依赖模型。

### D3 — approve.html 升级:能"合并到已有(已冻结)topic"
当前 approve.html 只加载新提案。升级为:**同时加载现有冻结词表**,把已有 topic 显示为"🔒 已冻结"且作为合并目标。每个新候选除 keep/丢弃/批内合并外,新增:
- **「合并到已有 C-xxxx」** → 把候选的 name+aliases **并进那个老 canonical 的 aliases**,**不建新卡、不占新 id**;
- D1/D2 标了 ⚠️ 的候选,在它旁边直接列出"疑似 = C-xxxx",一键合并。
导出时写**整张更新后的 `keyword_table.jsonl`**(老行可能多了别名 + 真正的新行),整体单调增长。

### D4 — 别名回填(学习闭环,最关键)
凡被判为"同一个"的新表面形(无论 AI 自动映射、还是人在 D3 手动合并),**一律写回老 canonical 的 `aliases`**。
→ **下次**这个叫法出现时,reduce 直接命中、不再走 AI。**词表越用越聪明,碎片化概率随时间下降而不是上升。**

> **boundary 是裁判**:D1–D3 判"是不是同一个",很大程度看老 topic 的 `boundary` 写得清不清。维护好 boundary,是这套防线的地基。

---

## 4. 标准操作 loop(每来一页 / 一批)

```
1. ingest + map 新页（走 12 的结构感知抽取）
2. discover（吃完整现有词表）→ 产 proposed_keywords.json，每个候选带 nearest_existing + dup_warning
3. approve.html：
     - 先看 ⚠️ 疑似重复 → 能合的「合并到已有 C-xxxx」（D3）→ 别名回填（D4）
     - 真新的 → 批准为新行（新 canonical_id）
     - 导出整张更新后的 keyword_table.jsonl
4. reduce：老 topic 自动并入老卡（路 A）、新 topic 出新卡（路 B）
5. 抽查：有没有"两张卡讲同一个东西"——若有，回 D3 合并、补别名/ boundary
```

---

## 5. 谁实现什么

| 谁 | 做什么 |
|---|---|
| **opencode** | D1:discover 输出 `nearest_existing`;D2:`DiscoverService` 加确定性 fuzzy 去重预检,写 `dup_warning` 进 `proposed_keywords.json`;(可选)reduce 只重算受影响 canonical 的增量模式 |
| **claude(我)** | D3:升级 `frontend/approve.html`——加载现有冻结词表、支持「合并到已有」、别名回填、导出整张更新表 |
| **Ethan(你)** | 审 ⚠️ 疑似重复、决定合并、**维护 boundary**(防线地基) |

---

## 6. 残余风险与后续(诚实说明)

- D2 的字符串去重挡得住**表面变体**,挡不住**语义近义但用词完全不同**(如 "Portal" vs "管理门户入口")。PoC 阶段靠 D1(AI 报告)+ 人审兜;**后续可上 embedding 相似度**(把候选 vs 现有 topic 算向量近邻)做语义级去重——内网已有 embedding,接上即可,属增量增强,不阻塞当前。
- 跨语言别名(中英混)建议显式进 `aliases`。
- 词表长大后,建议**定期人工对一遍** near-duplicate(用 D2 的 pairwise 相似度出一张"疑似重复清单"),做一次性合并清理。

---

*配套:解耦与闸 `09`;抽取层 `12`;验收 `10`;字段设计 `卡片字段说明_与Business核对.md`。本文件聚焦"多页、随时间、不碎片化"。*
