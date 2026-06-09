# 指令(给 opencode):把 reduce 拆成「topic 发现=提案」+「建卡=只匹配」两段

> **读者:opencode(内网编码 agent)。** 本文件是一份可直接执行的改造指令。
> **语言约定**(沿用全仓库):中文讲解,字段名 / JSON / prompt 一律英文。
> **谁下的指令:Ethan**(协调人)。改完请按 §9 回报你实际改了哪些文件、与本文档有何出入。

---

## 0. 一句话目标

把当前「边发现 topic 边建卡」的一体化 `reduce`,拆成**两段、中间加一道人工闸**:

```
ingest → map → [discover: 只产候选词表, 不建卡] → 〈人工冻结/审批〉 → reduce: 只匹配冻结词表建卡 → load
```

- **discover**:复用你写的 `backend/reducer/discovery.py`,但**降级为"提案器"**——只产出一份**候选 topic 词表 + 证据**,写盘给人看,**绝不直接生成 cards、绝不铸造进卡片的 canonical_id**。
- **人工闸**:Ethan/Business 审一遍候选词表,改名/合并/删除/标 subsection,**冻结成 approved 词表**(`paths.keyword_table` 指向的文件)。
- **reduce**:**恢复原始仓库的"只匹配不造词"行为**——只把 section 归到**冻结词表里已有的** canonical,匹配不到的进 `review_queue`,**不再创建 `C-AUTO-*`**。卡片的丰富结构(overview/details/subsections/按 topic_class 派生字段等)**保留**,只是 topic 集合此刻是冻死的。

**为什么这样改**:你在 `08_CURRENT_INTEGRATED_FLOW_ZH.md` §7 已经正确诊断出乱的根因——reduce 在"主动发现 topic"且约束不稳(命名漂移、粒度边界漂移、section 不纯导致 topic 互相污染)。根因是**"发现"和"建卡"被揉进同一步、且中间没有把 topic 集合固定下来的闸**。本指令不删除你的发现能力,而是把它移到闸的前面、让人来固定 topic 集合。这是原始仓库 `card-reduce/SKILL.md` §1 本来的设计(discover → proposed → 人审 → approved → match),原始代码只实现了 match 那一半,你实现了 discover 那一半,现在把两半按正确顺序接起来。

---

## 1. 目标架构(务必先理解这张图)

```
                                   ┌─────────────────────────────────────────────┐
  map_*.json ──┐                   │  人工闸(Ethan/Business)                      │
               ├─►  discover  ──►  │  审 proposed_keywords_review.md              │
  (refs body_md 仅供取证, 可选)     │  改名/合并/删/标 subsection → 冻结            │
               │   产出:           └──────────────────┬──────────────────────────┘
               │   proposed_keywords.jsonl            │ 冻结成 approved
               │   proposed_keywords_review.md        ▼
               │                          paths.keyword_table (approved, 固定不变)
               │                                      │
               └──────────────────────────────────►  reduce(只匹配)  ──► cards / inverted_index / review_queue
```

**两条铁律:**
- **R1 — 建卡阶段的 topic 集合 == 冻结词表,一个不多一个不少。** cards 里出现的 `canonical_id` 必须全部来自冻结词表;`reduce` 阶段**禁止**新建 canonical(包括 `C-AUTO-*`)。
- **R2 — discover 不建卡。** `discover` 的产物只有候选词表 + 给人看的 review 表,不写 `outputs/cards/`。

---

## 2. 你要做的改动(分阶段、文件级)

> 原则:**最小改动 + 不要重写已经能用的合成逻辑**。本次改的主要是**接线(wiring)和闸**,不是重写卡片合成。

### 阶段 1 — 把 discovery 降级为「全局提案器」

**1.1 改触发方式:让 discover 成为独立步骤,不再由 reduce 内部调用。**
- 在 `backend/pipeline.py` 的命令里**新增 `discover`**(放在 `map` 和 `reduce` 之间),仿照现有 `run_map` / `run_reduce` 的写法新增 `run_discover`。
- `reduce` 命令里**移除对 discovery 的调用**(见阶段 2)。

**1.2 把 discovery 从「每个 section 各自发现」改成「全局聚类一次」。**
这是治"命名漂移/互相污染"的关键。现状(你 08 文档 §6.5 第三步)是**对每个 section 调一次** discovery,所以每段各自造名 → 漂移。改成:
1. 读所有 `map_*.json`,收集全切片的 `keywords_raw` + `concepts`(去重),得到一张"原始叫法大清单"。
2. 连同**当前 approved 词表**(若已有)一起,**做一次(或分批)全局聚类调用**(prompt 见 §5.1),让模型:能归到已有 canonical 的就归;剩下的聚成簇,每簇给一个 `canonical_name` + `aliases`;拿不准的进 `needs_review`。
3. `body_md`(从 refs 读回)**只在需要给候选 topic 附证据片段时取用**,不要让 body_md 成为造 topic 的主驱动。

**1.3 产出候选词表,不产 cards。** 写文件:
- **`outputs/proposed_keywords.json`(必须,给审批工具 `frontend/approve.html` 读)**——格式 `{"candidates":[...], "modules":[...]}`,`candidates` 每项 schema 见 §4.1,`modules` 为本切片的受控 module 清单(给工具下拉用)。也可直接是候选数组,工具两种都吃。
- (可选)`outputs/proposed_keywords.jsonl` / `proposed_keywords_review.md`:纯文本速览,可复用 `canonicals.render_registry_markdown` 风格。

> **审批工具已在外网写好并验证**:`frontend/approve.html`(单文件、双击即开、离线可用)。它读 `proposed_keywords.json`,让人点选保留/合并/降级 subsection/改字段,一键导出符合 §4.2 的 `keyword_table.jsonl`。**你(opencode)只需保证 discover 吐出的 `proposed_keywords.json` 字段名对得上 §4.1。**

**1.4 候选 id 用临时前缀 `C-PROP-*`**(例如 `C-PROP-0001`),`status="proposed"`。**临时 id 不得进入任何 card**——它们只活在 proposed 文件里,等人工冻结时才被赋予稳定 id。

### 阶段 2 — reduce 恢复「只匹配不造词」,但保留卡片丰富度

**2.1 reduce 不再调用 discovery、不再读 refs 来发现 topic。** topic 集合只来自冻结词表(`paths.keyword_table`,经 `load_vocabulary` 读入)。

**2.2 归类用「只匹配」prompt**(见 §5.2,直接采用原始仓库 `REDUCE_NORMALIZE_SYSTEM` 原文):
- 每个 section 只能归到**冻结词表里已有的** `canonical_id`。
- 模型返回了不在词表里的 id → 直接报错(原始 `service.py` 就是这么校验的:`Unknown canonical_ids returned by LLM`)。
- 归不上的 section → 进 `review_queue`(类型 `unmatched-section`),**不要**自动建 canonical。

**2.3 删除/禁用 `C-AUTO-*` 铸造路径。** 全局搜 `C-AUTO`,把"匹配不到就造新 canonical"的分支改成"匹配不到就进 review_queue"。

**2.4 卡片合成保留你现在的成果,但只围绕"已匹配的 canonical"展开:**
- 顶层字段(`topic_class` / `module` / `boundary` / `topic_type` / `aliases` / `keywords_raw_agg` / `concepts_agg` / `questions_agg_*` / `source_section_ids` / `subsections` / `fields` / `flags`)**保留**。
- 按 `topic_class` 派生字段(workflow→trigger/preconditions/steps/outputs;system_component→purpose/capabilities/dependencies;catalog→categories/service_options/sla_or_performance/cost_or_rate)**保留**。
- **唯一的变化**:这些内容是从"归到该 canonical 的那批 section"里**确定性地填充**的,不再依赖 discovery 现场吐出的 topic。
- **三档 tier(narrative/inline-value/pointer-only)与每条带 `sources` 锚点的规则,绝不能动。** 精确值仍然只逐字搬(inline-value)或只留指针(pointer-only),禁止"总结的总结"。

**2.5 subsection 也走闸。** subsection 的"有哪些、叫什么、是不是该升成一级 topic"由**冻结词表**决定(人工在阶段 1.5 标注),reduce 只**填充内容**(summary/evidence_keywords/source_section_ids/details/key_points),不自己决定层级。这样治你 08 文档 §7.3 的"该挂 subsection 却被升成一级 topic"。

### 阶段 3 — (次要,顺手做)evidence 清洗

> 优先级低于阶段 1–2。目的:治你 08 文档 §8.6 的"问句残留 / Q&A 句式残留 / 片段拼接痕迹"。

- 在把 section 内容填进 card 字段前,做一道清洗:去掉以 `?`/`？` 结尾的问句、`Q:`/`A:` 句式前缀、明显的列表项拼接残渣。
- narrative 字段允许 LLM 改写成连贯陈述句;**inline-value 字段不许改写**(只能逐字搬),清洗仅限去除明显噪声前后缀。

### 人工闸(阶段 1 与 2 之间,Ethan 做,非 opencode)

> 写在这里是为了让你(opencode)知道 reduce 的输入从哪来、格式要对得上。
- Ethan 用 **`frontend/approve.html`** 打开 `outputs/proposed_keywords.json`:点选保留/丢弃、合并重复候选、把某候选降级为另一个 topic 的 subsection、补 `boundary`/`module`/`topic_class`,点「重新编号」把 `C-PROP-*` 换成稳定 `C-####`,再「导出」得到 `keyword_table.jsonl`(工具保证语法与 §4.2 schema)。把它放到 `paths.keyword_table` 指向的位置。`status` 由工具统一写 `approved`。
- 冻结后 reduce 才跑。**reduce 启动时若 `paths.keyword_table` 不存在或没有 approved 行,直接报错并提示"请先跑 discover 并冻结词表",不要静默回退到自动发现。**

---

## 3. 数据契约(schema)

### 4.1 `outputs/proposed_keywords.jsonl`(discover 产出,每行一个候选 topic)

```json
{
  "canonical_id": "C-PROP-0001",
  "canonical_name": "Message Inventory",
  "aliases": ["message inventory", "message list"],
  "topic_summary": "一句话:这个候选 topic 讲什么(给人审用)。",
  "evidence_keywords": ["message type", "producer", "consumer"],
  "suggested_module": ["Template & content standard"],
  "suggested_boundary": "消息类型清单及生产/消费关系;不含具体投递配置。",
  "suggested_topic_type": "inventory",
  "suggested_topic_class": "catalog",
  "suggested_subsections": ["Message Type", "Producer/Consumer Mapping"],
  "source_section_ids": ["160033#Message Inventory > Types"],
  "support": 4,
  "status": "proposed",
  "needs_review_reason": ""
}
```
- `support` = 命中该候选的 section 数,给人按热度排序审。
- `suggested_*` 全是**建议值**,人工冻结时可改。
- 模糊/拿不准的另起 `status="needs_review"` + 写 `needs_review_reason`,不要硬塞。

### 4.2 冻结后的 `paths.keyword_table`(approved 词表,reduce 的输入)

沿用原始仓库 `fixtures/keyword_table.jsonl` 的格式(`load_vocabulary` / `normalize_concept` 已支持 jsonl/json/md):

```json
{"canonical_id":"C-0101","canonical_name":"Message Inventory","aliases":["message inventory"],"module":["Template & content standard"],"topic_type":"inventory","topic_class":"catalog","boundary":"消息类型清单及生产/消费关系;不含具体投递配置。","subsections":["Message Type","Producer/Consumer Mapping"],"confidence":0.9,"status":"approved"}
```
- `canonical_id` 稳定(人工赋 `C-####`),`status="approved"`。
- 若你的 `normalize_concept` 还没读 `topic_class` / `subsections` 两列,请补上读取(向后兼容:缺列时给默认空值)。

### 4.3 card(保留你现在的结构,只强调约束)

- 顶层与 fields 结构沿用你 08 文档 §8.2–§8.4 的现状。
- **强约束**:`canonical_id` ∈ 冻结词表;每个 field 必须有 `tier` ∈ {narrative,inline-value,pointer-only} 且带 `sources[]`(`page_id`/`anchor`/`source_url`/`confluence_version`);inline-value 必有逐字 `value`;pointer-only 必有 `pointer_to` 且 `value=null`。

---

## 5. Prompt(直接用)

### 5.1 discover 全局聚类 prompt(提案器;采自原始 `card-reduce/SKILL.md` §3.1,按"提案不建卡"调整)

```
SYSTEM:
You are PROPOSING canonical topic candidates for human review. You are NOT building cards.
Given (a) a list of raw keyword/concept strings collected verbatim from many sections, and
(b) the list of already-approved canonical concepts, return STRICT JSON.

1) Map each raw term to an existing approved canonical_id when it clearly refers to the same thing.
2) Cluster the remaining raw terms: each cluster = ONE candidate topic. Pick a canonical_name
   (the clearest full form) and list the rest as aliases.
3) If a term is AMBIGUOUS or you are unsure, DO NOT force a merge — put it in "needs_review".
4) Prefer FEWER, well-scoped candidates over many near-duplicates. A candidate name should
   correspond to "one thing in the user's mind". When unsure about granularity, prefer merging
   and proposing the finer item as a suggested_subsection rather than a separate topic.

Return:
{
  "mapped":       [{"raw": "...", "canonical_id": "..."}],
  "candidates":   [{"canonical_name":"...","aliases":["..."],"evidence_keywords":["..."],
                    "suggested_subsections":["..."]}],
  "needs_review": [{"raw": "...", "reason": "..."}]
}

Rules:
- Treat an uppercase abbreviation near a full name as an alias candidate, not a new topic
  (e.g. "DMP" ~ "DM plugin").
- Do not invent concepts absent from the supplied raw list.
- Do NOT output cards, fields, summaries-of-summaries, or any final canonical_id.
```

> 说明:把全切片的 `keywords_raw`+`concepts` 一次性(或分批,但最后合并去重)喂进去,**而不是每个 section 调一次**。命名只在这里决定一次,从源头消除漂移。

### 5.2 reduce 归类 prompt(只匹配;直接采用原始仓库 `REDUCE_NORMALIZE_SYSTEM` 原文)

```
task: card_reduce_normalize_section
You are normalizing keyword variants into canonical concepts for a knowledge
base. Given one extracted section and already-approved canonical concepts,
return STRICT JSON.

Return:
{
  "canonical_ids": [string],
  "needs_review": [{"raw": string, "reason": string}]
}

Rules:
- Only use the supplied approved canonical concepts. Do not discover or create
  new topics; unmatched content must go to needs_review for the upstream owner.
- Map the section only to existing canonical_id values when the concept is the
  section's main subject, not a passing mention.
- If a term appears only as a cross-reference such as "see X" or "refer to X",
  do not assign ownership to X; leave it for soft_links.
- Match using heading_path, concepts, and the section's primary keywords. Do not
  use "mentioned anywhere" as sufficient evidence.
- Use each topic's boundary to reject ambiguous or out-of-scope matches.
- Ambiguous keywords must go to needs_review instead of being forced into a
  canonical.
- Do not invent concepts absent from the supplied section.
```

---

## 6. 必须保留、不要动的东西(避免过度重构)

- ✅ ingest / chunk / map 三层**完全不动**(map 仍逐 section 抽 keywords_raw/concepts/tier/fact_value/summary/questions)。
- ✅ 三档 tier 机制、每条 claim 带 `sources` 锚点——**这是全方案最有价值的设计,绝不能动**。
- ✅ 卡片的丰富字段(overview/details/key_points/examples、按 topic_class 派生字段、subsection 结构)——保留。
- ✅ 冲突处理(取新 + `conflict_detail` + 进 review_queue)——保留。
- ✅ `module` 多标签、`soft_links` 软链接——保留。
- ❌ 不要在 reduce 阶段做任何 topic 发现/新建 canonical。
- ❌ 不要让 discover 产出 cards。

---

## 7. 验收标准(怎么算改对了)

1. **新增 `discover` 步骤**:`... discover` 能产出 `outputs/proposed_keywords.jsonl` + `proposed_keywords_review.md`,且**不**生成任何 `outputs/cards/*`。
2. **闸生效**:在没有冻结词表时直接跑 `reduce` → **报错并提示先 discover+冻结**,不静默自动发现。
3. **建卡只匹配**:用一张冻结词表跑 `reduce` → 所有 card 的 `canonical_id` 都 ∈ 冻结词表;全仓库 grep `C-AUTO` 在 `outputs/cards/` 里**零命中**。
4. **幂等**:同一冻结词表 + 同一 map 产物,连跑两次 `reduce`,cards **逐字节一致**(确定性)。
5. **粒度稳定**:同一 map 产物连跑两次 `discover`,候选 topic 的**命名与数量基本一致**(全局聚类 + 去重后应收敛;若用真 LLM 有轻微抖动,以"人审的是同一批簇"为准)。
6. **回归**:原始仓库的 schema 校验(`validate_card` 等)与既有测试仍全绿。

---

## 8. MDC 单页 + 大表格的特别提醒

你们当前 capture 只有**一页**(MDC Project Check List),它是 Business 的总结页,含:① Channel × 属性 的大矩阵表(Channel=PN/SMS/Email/Letter/WhatsApp,列=Information/Template Maintenance/Delivery Mode·SLO·RTB Cost/...);② General Enquiries 的 Q&A;③ MDC Engagement & Requirement Process。两点要注意:

- **矩阵表别当一段叙述切。** 按 H2/H3 切,这张表很可能整张落进一个超大 section,map/discover 都会糟。建议在 ingest 阶段**把矩阵按"每个 Channel 一行 / 每个单元格一个事实"展开**,每个单元格带 `(channel, attribute)` 元数据,再进 map。这样 discover 抽出的候选才是干净的名词(渠道名、属性名),而不是一坨。
- **"从这页抽名词 → 拿名词去别页抽"正是本指令的 discover→冻结→match 流程的真身**:第一轮在 MDC 这页跑 `discover` 得到候选名词 → 人冻成词表 → 后续把别的页 ingest/map 进来后,用同一张冻结词表 `reduce`,名词就会稳定地把别页内容归过来。**不要再让每页各自发现名词。**

---

## 9. 如果现状和本文档不符 / 请回报

本指令基于 `08_CURRENT_INTEGRATED_FLOW_ZH.md` 的描述写成,可能与你内网代码的实际形态有出入。请你:
1. 先**只读不改**,核对:`reducer/service.py` + `discovery.py` 当前到底在哪一步调 discovery、在哪一步铸造 `C-AUTO-*`、card 合成函数叫什么。
2. 按本文档**最小改动**实现"两段 + 闸",**优先保证 §7 的验收标准**,实现手段可因地制宜。
3. 改完回报一份简短 diff 说明:**改了哪些文件、§7 每条是否通过、有没有发现本文档没预料到的耦合**。把这份回报交回给 Ethan(可拍照或另写 md)。

---

*配套背景(外网旧仓库,供对照):原始 reduce 的"只匹配"实现见 `backend/reducer/service.py` 的 `REDUCE_NORMALIZE_SYSTEM` 与 `_normalize_section`;词表读取见 `backend/reducer/canonicals.py` 的 `load_vocabulary`/`normalize_concept`;原始设计意图见 `card_ingestion_sop/skills/card-reduce/SKILL.md` §1、§3.1。*
