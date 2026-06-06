# 合并对接(同事词表)+ module facet —— 给 codex 的改造说明

> **读者:** codex(内网外改代码)。
> **背景:** "key topics + keyword list + module 域分区"由**同事的组件**产出、Business 审批。我们**不再自己生成词表**(原 `reducer/canonicals.py` 里硬编码的 7 条种子要去掉),改成**读同事那张审批过的表**;并把 `module` 作为一个**多标签元数据 facet** 贯穿全流程。
> **两条铁律(用户已拍板):**
> 1. **绝不删页** —— module 只是标签,不做摄取/检索阶段的删页过滤。低价值页用 `card_worthy=false` 标记,但仍可被 RAG 检索到(保住长尾 + 新人 + association recall)。
> 2. **module 多标签** —— 一个 page / section / card 可属于多个 module。
> **语言:** 注释中文;字段名/JSON/代码英文。

---

## 1. 接合契约:`keyword_table`(同事产出 → 我们 reduce 读)

唯一接合点 = 一张表。同事写、我们读。先两边对齐它的**列**和**文件格式**。

### 1.1 列映射(她的表 → 我们的字段)

| 同事的列 | 映射到我们的 | 用途 |
|---|---|---|
| `topic` | `canonical_name` | 卡片/分组的规范名 |
| **(aliases?)** | `aliases: []` | **★见 §1.2,最关键的缺口** |
| `module`(多个) | `module: []` | 多标签 facet(§2) |
| `type` | `topic_type`(原样留) | 分类提示,不参与分组 |
| `confidence` | `confidence` | 低分 → 进 review_queue / 标注 |
| `why useful` | `note_useful` | 给 Business/人看 |
| `topic boundary` | `boundary` | **喂归类**:帮 reduce 判一段属不属于该 topic,减少歧义错(如 OTP) |
| `related page` | `related_pages: []` | **独立的 topic→page 真值**:校我们的倒排表 + 喂 `association_recall`(§3.7) |
| `review note` | `review_note` | Business 备注 |
| (无则我们分配) | `canonical_id` | 稳定主键,导入时分配、永不复用/改 |
| (默认 approved) | `status` | 只用她审批过的行;未审的不进 reduce |

### 1.2 ★必须先确认的缺口:aliases(别名)

我们的 `card-reduce` 是靠**"原文里的原始叫法 → 匹配 `canonical_name` + `aliases`"** 来把 section 归到 topic 的。
**如果她的表只有 `topic`(规范名)、没有别名/同义词列**,那么 `DMP`、`Data Management plugin` 这些就归不进 `DM Plugin`,归类大面积失败。

→ 三选一,**和她确认**:
1. 她的表加一列 `aliases`(每个 topic 的常见叫法/缩写/拼写变体)——**最优**;
2. 她的 keyword list 本身就是"别名级"的词(那就把多行同义词折叠到一个 canonical);
3. 都没有 → 我们在 reduce 前加一小步**别名解析**(用 gpt-5.5 给每个 topic 生成候选别名,人工/她确认)。代价最高,尽量避免。

> codex:按"她有 aliases 列"实现读取;同时留一个 `--resolve-aliases` 兜底开关(方案 3),默认关。

### 1.3 文件格式 + 路径(建议)

一行一个 topic 的 JSONL,放约定路径(默认 `inputs/keyword_table.jsonl`;也兼容现有 `card_ingestion_sop/templates/canonical_keywords_受控词表.md` 的表格,二选一,配置 `paths.keyword_table` 指定)。

```json
// inputs/keyword_table.jsonl  —— 同事产出、Business 审批;我们只读
{"canonical_id":"C-0007","canonical_name":"DM Plugin","aliases":["DM plugin","Data Management plugin","DMP"],
 "module":["Integration & API standard","Delivery & tracking standard"],
 "topic_type":"component","confidence":0.9,
 "boundary":"消息投递核心插件,不含 Journey 编排","related_pages":["123456","777001","160033"],
 "note_useful":"投递链路核心","review_note":"DMP 缩写已确认","status":"approved"}
```

---

## 2. `module` facet 规则(多标签 · 不删页)

- **定义**:粗粒度域标签,取值来自同事的 6 个 module(`Channel standard / MDC development guideline / Template & content standard / Integration & API standard / Delivery & tracking standard / Operations & release standard`),**可多个**。
- **来源 / 怎么落到 page、section、card 上**:
  - **card**:直接继承其 topic 的 `module`(来自 keyword_table)。
  - **section / page(给 RAG 过滤用)**:= 该页/段命中的所有 topic 的 module **取并集**(多标签);若同事另有"页→module"映射,优先用她的、再并我们的派生值。
- **不删页**:所有页照常 ingest。可选给"非任何业务 module / 低价值"的页/段打 `card_worthy=false`(或 `priority=low`)——**卡片只在有 module 的高价值内容上铺,RAG 仍能检索到全部原文**(卡片顶、原文底)。**不要**在 ingest/retrieve 里因 module 把页排除。
- **用途**:检索可选 `module` 预过滤(提精度);看板/评测可按 module 拆;新人按 module 当学习路径导航。

---

## 3. 代码改造点(codex 逐条,带文件)

> 这是把"硬编码种子词表"换成"读外部表"+ 让 `module` 多标签贯穿。改完 `python -m backend.pipeline demo` 仍要确定性通过。

1. **`reducer/canonicals.py` → 改成加载器(替换 CR-3)**:删掉硬编码 `CANONICALS` 7 条;新增 `load_vocabulary(path) -> dict[cid, concept]`,读 §1.3 的 `keyword_table.jsonl`(字段含 `aliases/module/boundary/related_pages/...`)。`canonical_ids_for(section)` 用**加载来的 aliases** 做匹配(不再写死规则)。只用 `status=approved` 的行。
2. **`config`**:加 `paths.keyword_table`(默认 `inputs/keyword_table.jsonl`);`providers` 不变。
3. **卡片 schema(`schemas/validation.py` + `reducer/service.py:build_card`)**:卡片加 `module: list[str]`(继承自 canonical)、可选 `boundary`。校验允许多值。
4. **倒排表(`reducer/service.py:inverted_row`)**:每行加 `module: list[str]`。
5. **归类质量(`reducer`)**:把 topic 的 `boundary` 一起喂归类判断(prompt 里给 boundary),降低 OTP 式误归。
6. **`load/service.py`**:refs 元数据加 `module: list[str]`(= 该 section 命中 topic 的 module 并集)+ 可选 `card_worthy`。
7. **store 适配器(多标签要小心)**:
   - `store_json` / `store_pgvector`:`module` 存为数组(pgvector 用 `text[]` + GIN 索引)。
   - **`store_chroma`:Chroma metadata 只能标量!** 多标签 module 要么拍平成分隔字符串(如 `"|Integration & API standard|Delivery & tracking standard|"`,过滤用 contains),要么每个 module 一个布尔列。别直接塞 list 进 Chroma metadata。
8. **`retrieve/service.py`:过滤要支持"成员包含"而非等值**。现在 `_matches` 是 `row.get(key) != value` 的等值判断;对 `module` 改成"`value ∈ row['module']`"(或 Chroma 的 contains)。`filters={"module": "Integration & API standard"}` 应命中含该 module 的行。
9. **eval / 看板(可选但推荐)**:
   - 用 keyword_table 的 `related_pages` 作为 `association_recall` 的**独立真值**(对比我们倒排表关联到的页)。
   - 报告/看板支持按 `module` 拆指标 + 一个 module 过滤器(给领导看"各域覆盖/质量"的故事)。

---

## 4. fixtures 配套(让合并后的链路离线就能验)

- 给 `fixtures/confluence/*.md` 的 front-matter 加 `module:`(**多标签**,体现一页多域,如 DM 页 = `["Integration & API standard","Delivery & tracking standard"]`)。
- 加一个 `fixtures/keyword_table.jsonl`(§1.3 格式,覆盖 DM/Journey/Adaptor/OTP/... + 多 module + aliases + related_pages),当作"同事审批表"的离线替身。
- demo 改成从该 fixture 读词表(`paths.keyword_table` 指向它),验证:① 不再依赖硬编码种子 ② 卡片/倒排/refs 带多标签 module ③ `retrieve --filter module=...` 能按域过滤 ④ 没有任何页被丢。

---

## 5. 验收清单(Definition of Done)

- [ ] 词表**从文件加载**,`reducer/canonicals.py` 无硬编码种子;只用 `status=approved` 行。
- [ ] aliases 缺口已和同事确认(三选一),reduce 能把 `DMP/Data Management` 归进 `DM Plugin`。
- [ ] `module` **多标签**贯穿 card / inverted / refs;`retrieve` 能按 module **成员包含**过滤;Chroma 多标签已正确拍平。
- [ ] **零删页**:11 页(真实里全量)都在;低价值用 `card_worthy=false` 标记而非剔除;RAG 仍可检索到。
- [ ] `related_pages` 接进 `association_recall`;看板可按 module 拆(可选)。
- [ ] `python -m backend.pipeline demo` 仍**确定性**通过;新增逻辑有测试(加载词表、多标签过滤、不删页)。

---

## 6. 与 `04_CODE_REVIEW.md` 的关系

- **CR-3 升级/改向**:原 CR-3 说"reduce 不发现新概念、要实现词表发现"。**现在发现由同事的组件负责**,所以 CR-3 改成:**把硬编码种子换成"加载同事的外部审批表"**(本文件 §3.1)。不要再在我们这边实现 discovery。
- 其余 CR-1/2/4/5… 不变,照 `04_CODE_REVIEW.md` 改。
- 合并的"谁产出 / 谁消费 / 边界"见 `card_ingestion_sop/README_数据摄取卡片SOP.md` §11。
