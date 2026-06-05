# 受控词表(Canonical Keywords Registry)

> **这是什么:** 一张"活"的关键词总表。它记录:每个概念的**规范名(canonical_name)**、它的**别名(aliases)**、一句话定义、以及审批状态。
> **谁产出:** 由 `card-map` 自报关键词 → `card-reduce` 归一化**自底向上长出来**;**Business 只负责审批**(不需要从零编写)。
> **为什么重要:** 它是 reduce 归一化的"标准答案"、是倒排表的合并键、也是 Business 一眼看懂"我们认为有哪些 topic"的清单。

---

## 给初学者:三个概念讲清楚

- **规范名 canonical_name**:我们**统一**用的那个名字。例:统一叫 `DM Plugin`。
- **别名 aliases**:同一个东西的其它叫法,检索/合并时都等同于规范名。例:`Data Management plugin`、`DMP`。
- **状态 status**:这条是不是被 Business 认可了。
  - `proposed` = AI 提出,**待 Business 审批**(新词默认这个)。
  - `approved` = Business 确认无误,可放心使用。
  - `merged` = 后来发现它其实是另一个概念的别名,已并过去(记 `merged_into`)。
  - `deprecated` = 不再用(如拼错、过时叫法)。

> **流程一句话:** AI 写 `proposed` → Business 审 → 对的改 `approved`,错的改 `merged`/`deprecated`(并触发一条 bad case)。

---

## 字段定义

| 列 | 含义 | 谁填 |
|---|---|---|
| `canonical_id` | 唯一编号,如 `C-0007`(永不复用) | reduce |
| `canonical_name` | 规范名 | reduce 提议 / Business 定 |
| `aliases` | 别名列表(分号隔开) | reduce 提议 / Business 增删 |
| `definition` | 一句话定义 | reduce 提议 / Business 修 |
| `component` | 所属组件域(`DM / journey / adaptor / common / OTP / SFMC / ...`,从切片里长出来) | reduce |
| `content_type_hint` | 主要内容类型倾向(`what-is/config/...`,仅提示) | reduce |
| `status` | `proposed / approved / merged / deprecated` | Business |
| `merged_into` | 若 `merged`,并入了哪个 `canonical_id` | Business |
| `source_pages` | 出现过的代表性 page(抽样,便于 Business 核) | reduce |
| `owner` | 该 topic 的业务对口人(可空) | Business |
| `last_reviewed` | 上次审批日期 | Business |
| `notes` | 备注(争议点、关联 bad case 等) | 任意 |

---

## 词表(示例 + 实际维护区)

> 下面前几行是**示例**(帮助理解格式),真实运行时按此格式增删。也可另存一份 `canonical_keywords.csv` 给程序追加,这份 md 作为人看的主视图。

| canonical_id | canonical_name | aliases | definition | component | content_type_hint | status | merged_into | source_pages | owner | last_reviewed | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C-0007 | DM Plugin | Data Management plugin; DMP | 把消息投递到各渠道的核心插件 | DM | what-is/config | approved | — | 123456; 777001 | alice | 2026-06-04 | DMP 缩写经 RQ-0011 确认;config 有版本冲突见 bad case reduce-001 |
| C-0008 | Journey Plugin | journey plugin | 编排用户旅程触发的插件 | journey | what-is/how-to | approved | — | 220110 | alice | 2026-06-04 | 与 DM 经 adaptor 衔接 |
| C-0009 | Adaptor | adaptor; adapter | DM 与 Journey 之间的衔接层 | adaptor | how-to | proposed | — | 123456; 220110 | — | — | 拼写 adapter/adaptor 并存,已合为别名,待 Business 确认主拼写 |
| C-0014 | MDC OTP Service | OTP service | MDC 的一次性密码服务 | OTP | what-is | proposed | — | 305001 | — | — | ⚠️ 注意与泛指 "OTP" 区分,见 RQ-0019 |
| C-0021 | ~~DMP Adaptor~~ | — | (误建,实为 DM Plugin 的缩写场景) | — | — | merged | C-0007 | — | — | 2026-06-04 | 由 bad case map-001 触发并入 C-0007 |

---

## 维护规则

1. **新概念默认 `proposed`**,出现在最近一次 reduce 的 `review_queue` 里,等 Business 审批。
2. **审批 = 改 status + 填 last_reviewed**。Business 在 `business_review_checklist` 上打勾/纠正后,你据此更新本表。
3. **判错别名/合并**:发现某别名其实是另一个概念 → 改对应行 `status`,必要时新建/并入,并**写一条 bad case**(`bad_case_library`),由 bad case 提炼出的规则回写 `card-reduce` §7。
4. **`canonical_id` 永不复用、永不改名**(改名只改 `canonical_name`,id 不动),保证倒排表/卡片的外键稳定。
5. **粒度纪律**:规范名对应"用户心里的一个东西"。变体太多别狂造新概念,宁可合并 + 卡片里留子条目。

---

## 与其他文件的关系

- 被 `card-map` 读(复用规范名);被 `card-reduce` 读写(归一化时回写新行)。
- Business 通过 `business_review_checklist_评审清单.md` 审批本表的 `proposed` 行。
- 错误归并通过 `bad_case_library_纠错案例库.md` 记录并改进 skill。
