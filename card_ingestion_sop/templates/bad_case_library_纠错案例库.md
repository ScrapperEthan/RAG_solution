# Bad Case 纠错案例库(SOP 的进化引擎)

> **这是什么:** 一个登记本。每当 Business 提出不同意见、或我们自己发现 map/reduce 出了错,就在这里记一条,并**提炼成一条通用规则**回写到对应 skill。
> **为什么是"引擎":** 这条反馈回路就是"SOP 不断优化"的具体机制。**没有这个本子,同样的错会一犯再犯。**

---

## 给初学者:一条 bad case 的一生

```
发现问题(Business 评审 / 自查 / eval)
      │
      ▼
登记 case(填下面的表)
      │
      ▼
判断:是"一次性的个案"还是"会重复的模式(pattern)"?
      ├─ 一次性 → 直接改数据(改卡片/词表),case 标 status=fixed,不必动 skill
      └─ 模式  → 提炼成一条【通用规则】 → 回写到 skill 的"已知 bad cases"区
                          │
                          ▼
                  加入 regression set(回归集)
                          │
                          ▼
                  重跑验证修好了 → status=fixed
```

> **最重要的一句话纪律(防过拟合):**
> **优先提炼"规则",而不是堆"例子"。** 一条条原始 case 全塞进 LLM 的 prompt,会让 prompt 越来越长、还会让模型只会处理见过的具体案例(过拟合)。
> 所以:能用一句规则覆盖的,就写成规则(skill 的"规则区");只有规则讲不清、必须靠样例的,才放进 skill 的"few-shot 区",且要克制。
> **原始 case 全部留在本案例库**(完整可追溯),但**不全量进 prompt**。

---

## 字段定义

| 字段 | 含义 |
|---|---|
| `case_id` | 编号,`map-NNN` / `reduce-NNN` / `route-NNN`(按出错阶段前缀) |
| `date` | 发现日期 |
| `stage` | 出错阶段:`map` / `reduce` / `选择层(retrieval/agent)` |
| `raised_by` | 谁发现的:`Business` / `自查` / `eval` |
| `input_excerpt` | 触发问题的原文/输入片段(够定位即可) |
| `wrong_output` | 当时错误的输出 |
| `correct_output` | 正确应当是什么 |
| `root_cause` | 根因(为什么会错) |
| `generalized_rule` | **提炼出的通用规则**(本库的灵魂);若纯属个案写"个案,不提炼" |
| `action_taken` | 改了哪个文件哪节(如 `card-map §5.1 加 map-R-001` / 词表 C-0021 并入 C-0007 / golden 加一题) |
| `pattern?` | 是否模式(决定要不要动 skill) |
| `regression_added?` | 是否已加入回归集 |
| `status` | `open` / `fixed` |

---

## 处置流程(怎么决定改哪里)

| 错的本质 | 改哪里 |
|---|---|
| 抽取规则错(类型判错、缩写当新概念、把"支持X"当成值) | 改 **`card-map` §5** + 必要时改 prompt |
| 合并/冲突/grounding 规则错 | 改 **`card-reduce` §7** + 必要时改 prompt 或卡片模板 §4 |
| 某个词归错、别名错 | 改 **受控词表** 对应行 |
| 模板缺字段 / 字段定义不清 | 改 **卡片模板**(`card-reduce` §4) |
| 答题 agent 该下钻却没下钻(漏钻) | 改 **选择层下钻规则**(讨论稿 §6.3),并在 eval 加一题 |
| 评测题本身有问题 | 修 **golden set**,记一笔 |

> **一条 bad case 可能同时触发多处改动**(如 `map-001` 既改 map skill 又改词表)。`action_taken` 把都写上。

---

## 案例(示例 2 条 + 实际登记区)

### case map-001(示例)
- **date** 2026-06-04 · **stage** map · **raised_by** Business
- **input_excerpt** SFMC Migration 页里写 "configure the DMP batch size ..."
- **wrong_output** map 把 `DMP` 抽成了一个**新概念** `concepts=["DMP"]`,与 `DM plugin` 并列。
- **correct_output** `DMP` 应作为 `DM plugin` 的**别名候选**放进 `keywords_raw`,不新建概念。
- **root_cause** map 不认识 `DMP` 是 `DM plugin` 的缩写,默认当成新词。
- **generalized_rule** 大写缩写且语境靠近某全称 → 当别名候选,不新建概念;是否等同交给 reduce + Business。
- **action_taken** `card-map` §5.1 新增 `map-R-001`;`card-reduce` §7.1 新增 `reduce-R-002`(缩写别名先 proposed);受控词表把误建的 `C-0021` 标 `merged → C-0007`。
- **pattern?** 是 · **regression_added?** 是(回归集加入该页片段) · **status** fixed

### case map-002(示例)
- **date** 2026-06-04 · **stage** map · **raised_by** 自查
- **input_excerpt** 某页写 "the DM plugin supports retry configuration"(只说支持,未给次数)
- **wrong_output** map 标成 `tier=inline-value` 且编了 `fact_value="max_retry: 3"`。
- **correct_output** 应标 `tier=pointer-only`(只知"可配 retry",值在别处),不编数值。
- **root_cause** 把"支持/可配置 X"误当成"X 的值"。
- **generalized_rule** "支持/可配置 X"不等于"X 的值";无确切值一律 pointer-only,绝不编数值。
- **action_taken** `card-map` §5.1 新增 `map-R-002`。
- **pattern?** 是 · **regression_added?** 是 · **status** fixed

### case reduce-001(示例)
- **date** 2026-06-04 · **stage** reduce · **raised_by** eval(一道 "DM plugin batch_size 默认?" 答错)
- **input_excerpt** 页 123456(v7)`batch_size=500`;页 777001(v3,更晚更新)`batch_size=1000`
- **wrong_output** reduce 取了 `500`(先看到的页),且**没标冲突**。
- **correct_output** 取**更新更晚**的 `1000` 作 `authoritative`,**并标 `conflict=true`** + 列两来源,进 review_queue。
- **root_cause** reduce 用"先到先得",没按 version/update_at 取新,也没冲突标注。
- **generalized_rule** 数值冲突一律按 version/update_at 取新 + 显式标注 + 进队列,禁止静默选值。
- **action_taken** `card-reduce` §7.1 新增 `reduce-R-001`;golden set 增一题(gold=权威页)。
- **pattern?** 是 · **regression_added?** 是 · **status** fixed

### (实际登记从这里往下加)
```
case ____-___
- date __ · stage __ · raised_by __
- input_excerpt:
- wrong_output:
- correct_output:
- root_cause:
- generalized_rule:
- action_taken:
- pattern? __ · regression_added? __ · status open
```

---

## 回归集(Regression Set)

> **作用:** 把每条"模式型"bad case 的输入留下来,每次改完 skill 后**重跑**,确认①这条修好了 ②没把别的搞坏。这样 skill 越改越稳,而不是按下葫芦浮起瓢。

- 形态:`outputs/regression/` 下一组小输入(几页 map 输入 / 几条 reduce 输入)+ 期望输出片段。
- 节奏:每次更新任一 skill 后必跑;定期(如每个切片收尾)整体跑一遍。
- 与 golden set 区别:**golden set 测"检索/答题效果"(面向最终指标);回归集测"抽取/合并行为"(面向 skill 正确性)**。两者都要,别混。

---

## 防过拟合 · 定期整理(重要)

- 每隔一段(如每收尾一个切片)回看 skill 的"规则区":能合并的规则合并、矛盾的修订、过时的删除。
- few-shot 区保持精简:只留规则讲不清的少数例子。其余原始 case 留在本库即可。
- 若某类 case 反复出现 → 说明 prompt/模板有结构性缺陷,优先改结构,而不是再加一条规则。

---

## 与其他文件的关系

- 上游来源:`business_review_checklist`(Business 反馈)、eval(golden set 失败项)、自查。
- 下游改动:`card-map` §5 / `card-reduce` §7 / 卡片模板 §4 / `canonical_keywords_受控词表.md` / golden set。
