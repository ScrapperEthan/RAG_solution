# 验收清单:opencode 完成「解耦 + subsection」后逐条核对

> **谁用**:Ethan(协调人),在内网把 opencode 的改动跑一遍、逐条打勾。
> **什么时候用**:opencode 按 `09_OPENCODE_解耦topic发现与建卡_指令.md` 改完后。
> **配套**:本清单是 09 文档 §7 的**可执行展开版**;不通过时回 09 对应小节修。
> **命令前缀**:下面用 `python -m backend.pipeline <cmd>`;内网若用 uv,则 `uv run python -m backend.pipeline <cmd>`。`<cmd>` 默认读 `config.yaml`。

---

## 0. 一句话验收目标

链路必须是两段 + 一道人工闸,且 **topic 集合冻结、subsection 真正落到卡上**:

```
discover(只提案,不建卡) → 〈approve.html 冻结词表〉 → reduce(只匹配,无 C-AUTO,幂等) → cards(含 subsection)
```

---

## 1. 按顺序跑一遍(命令速查)

```bash
# 1) 发现：只产候选，不产卡
python -m backend.pipeline discover
#    期望：生成 outputs/proposed_keywords.json；outputs/cards/ 没有新增/变化

# 2) 冻结：用 frontend/approve.html 打开上面的 json，审完导出 keyword_table.jsonl
#    放到 config.yaml 里 paths.keyword_table 指向的位置

# 3) 建卡：只匹配冻结词表
python -m backend.pipeline reduce
#    期望：outputs/cards/*.json 全部来自冻结词表，含 subsection

# 4) 幂等复跑（验收 C4 用）
python -m backend.pipeline reduce   # 第二次
```

---

## 2. 验收清单(逐条打勾)

### A. discover 层 —— 只提案,不建卡
- [ ] **A1** 跑 `discover` 后存在 `outputs/proposed_keywords.json`,且能被 `frontend/approve.html` 正常加载。
- [ ] **A2** 跑 `discover` **不**生成、不修改 `outputs/cards/*`(跑前后对比 cards 目录无变化,或此时 cards 尚不存在)。
- [ ] **A3** 候选用临时前缀 `C-PROP-*`,**没有**任何 `C-PROP-*` 混进最终卡或冻结词表。
- [ ] **A4** discover 是**全局聚类一次**而非每 section 各发现:同一个候选不会因出现在多个 section 而重复成多条;连跑两次,候选**命名与数量基本一致**(收敛)。

### B. 人工闸 / 词表
- [ ] **B1** `approve.html` 能加载 A1 的 json,合并/降级 subsection/改字段/导出都正常。
- [ ] **B2** 导出的 `keyword_table.jsonl` 每行是**合法 JSON**,含 `canonical_id / canonical_name / aliases / module / topic_type / topic_class / boundary / subsections / status:"approved"`。
- [ ] **B3** 放到 `paths.keyword_table` 后,`load_vocabulary` 能读、不报错(canonical_id 无重复)。
- [ ] **B4** **闸生效**:把词表临时移走或清空再跑 `reduce` → **报错并提示"先 discover 并冻结词表"**,绝不静默回退到自动发现。

### C. reduce 层 —— 只匹配 + 幂等
- [ ] **C1** 用冻结词表跑 `reduce` 成功产卡。
- [ ] **C2** **零 C-AUTO**:`grep -rl "C-AUTO" outputs/cards/` **无命中**;每张卡的 `canonical_id` 都 ∈ 冻结词表。
- [ ] **C3** 归不上的 section 进 `outputs/review_queue.jsonl`(type=`unmatched-section`),**没有被硬塞**进某个 canonical。
- [ ] **C4** **幂等**:同词表 + 同 map 产物,连跑两次 `reduce`,`outputs/cards/` **逐字节一致**(`git diff --stat outputs/cards/` 或目录 diff 为空)。

### D. cards 内容 —— 保留丰富度 + 三档 tier + 清洗
- [ ] **D1** 卡片保留丰富字段:`definition/config/troubleshoot/related_components` + `overview/details/key_points/examples` + 按 `topic_class` 派生(workflow→trigger/steps/outputs 等)。
- [ ] **D2** 每个 field 有 `tier` ∈ {narrative, inline-value, pointer-only},且带 `sources[]`(每项含 page_id/anchor/source_url/confluence_version)。
- [ ] **D3** `inline-value` 有逐字 `value`;`pointer-only` 的 `value=null` 且有 `pointer_to`。
- [ ] **D4** 冲突字段:**取新** + `conflict_detail` 列出各来源各值 + 同时进 `review_queue`(不静默选值)。
- [ ] **D5** **evidence 清洗**:抽 3 张卡,字段值里**没有**问句残留(以 `?`/`？` 结尾)、**没有** `Q:`/`A:` 句式、**没有**明显的片段拼接残渣。

### E. subsection —— §4.4 的三处必须全接通
- [ ] **E1 读**:词表里带 `subsections` 的 topic,卡里**确实出现了**对应 subsection(没被静默忽略)。
- [ ] **E2 填**:每个 subsection 子块至少有 `name` + `sources`,内容来自归到该子成员的 section。
- [ ] **E3 层级对**:抽查 `Testing→WPB(O63)/WSB(O63&O88)`、`Channel Support→PN/SMS/Email/…` 是否挂在**对的父 topic** 下;**没有**"该当 subsection 却被升成一级 topic"或反之。
- [ ] **E4 校验**:`validate_card` **放行**顶层 `subsections`(空 `[]` 也行);故意造一个缺 `name`/`sources` 的子块 → **会报错**。
- [ ] **E5** subsection 内的精确值**同样守三档 tier**(逐字搬或留指针,没二次总结)。

### F. 回归 —— 别把能用的改坏
- [ ] **F1** 原有测试全绿(`pytest` 或既有回归脚本)。
- [ ] **F2** schema 校验全部通过(`validate_card` / `validate_map_page` / `validate_inverted_row` 不抛错)。
- [ ] **F3** `ingest` / `map` 行为未变(本次只应动 `discover` / `reduce` / `normalize_concept` / `validate_card`)。

---

## 3. 抽样人工核查(eyeball,约 5 分钟,不能纯靠自动)

随机抽 3–5 张卡,对着原文确认:
1. **归类对不对**:这张卡的 section 是不是真讲这个 topic(没有把别的内容误归)。
2. **精确值是不是真的**:卡里的 `inline-value`(数字/错误码/参数)逐字回原文核一遍,确实一致。
3. **subsection 合不合理**:二级成员该不该挂在这个父 topic 下。
4. **交叉引用没误判**:原文里"see X / refer to X"这种,X **没有**被错当成归属(应只在 soft_links)。

---

## 4. 让 opencode 交回的回报(模板)

> opencode 改完,连同下面这份回报一起交回(拍照或另写 md):

- **改了哪些文件**(列文件名 + 一句话说明)。
- **A–F 每条 pass / fail**(失败的写原因)。
- **意外耦合**:有没有发现 09 文档没预料到的依赖/改动点。
- **样例三连**:贴 `proposed_keywords.json` 一段 → 冻结后 `keyword_table.jsonl` 同一 topic 一行 → 最终该 topic 的 card(含一个 subsection)一段。

---

## 5. 任一条不通过 → 回哪修

| 不通过项 | 多半是哪没做对 | 回 09 文档 |
|---|---|---|
| A2 | discover 还在建卡,没解耦干净 | §2 阶段1、R2 |
| A4 | 还是每 section 发现,没改全局聚类 | §2 阶段1.2、§5.1 |
| B4 | reduce 没加"无词表就报错"的闸 | §2 阶段2、人工闸段 |
| C2 | 还在造 `C-AUTO` | §2 阶段2.3、R1 |
| C4 | 不幂等(有随机性/没固定顺序) | §7 验收④ |
| D5 | evidence 清洗没做 | §2 阶段3 |
| E1–E5 | §4.4 的"读/填/校验"三处没接全 | §4.4 |
| F* | 误改了 ingest/map 或破坏了 schema | §6 必须保留清单 |

---

*配套:架构与改造细节见 `09_OPENCODE_解耦topic发现与建卡_指令.md`;集成版现状与问题诊断见内网 `08_CURRENT_INTEGRATED_FLOW_ZH.md`;卡片字段设计见 `卡片字段说明_与Business核对.md`。*
