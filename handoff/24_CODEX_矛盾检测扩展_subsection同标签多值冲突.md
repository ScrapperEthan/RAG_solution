# 24 CODEX 后端规格：矛盾检测扩展（subsection 同标签多值冲突）

**给 codex（外网仓库 `backend/reducer/`）。claude 写规格，codex 实现，claude review。** 含 §6 opencode 内网移植说明（Ethan 手动拷进内网）。

> 灵感来自 `llm-wiki-agent` 的 "contradiction flagging at ingest time"，但落进**本系统已有的 review_queue + 人工冻结闸**纪律里：**检测出冲突就排队让人裁决，绝不悄悄伪造一个"正确值"**。

## 0. 现状：矛盾检测**已有一半**（别重复造）
`merge_config_field`（[backend/reducer/service.py:457-498](../backend/reducer/service.py)）**已经**做了一类冲突检测：
- 仅针对 `info_type=="config"` 且 `fact_values` 形如 `name: value` 的字段；
- 同一 `name` 出现多个不同值时：按 `update_at`/`confluence_version` 选最新作为展示值，把冲突写进 `field.conflict_detail` + 经 `conflict_item`（[service.py:629](../backend/reducer/service.py)）进 `review_queue` + 卡上打 `flags`（[service.py:199-201](../backend/reducer/service.py)）。

**保留它，不要改它。** 本规格只补它覆盖不到的那类冲突。

## 1. 缺口：subsection 级 fact 的同标签多值冲突
MDC 多页抽取里最常见的冲突是——**同一个 subsection 标签（如某 channel × 某属性）在不同 section 给了不同的叶子值**（例：`SLO` 在 A 页是 `4h`、B 页是 `8h`；某 `Contact Point` 两页给了不同人名）。

当前 `build_subsection_facts`（[service.py:318-338](../backend/reducer/service.py)）+ `_subsection_row`（[service.py:280-290](../backend/reducer/service.py)）只在**完全相同**时去重（`dedupe_facts`），**值不同就并排留着、不标冲突**。这类要补检测。

## 2. 要实现什么
在 subsection facts 组装完成后，**按 `label`（normalize 后）分组**，对 `tier ∈ {inline-value, narrative}` 且**有 `value`** 的 fact：
- 若同一 label 下出现 **>1 个不同的 `value`**（用 `clean_inline_value` 后的字符串判定）→ 判为 **fact 冲突**。
- 处理方式**对齐 `merge_config_field`**：
  - **展示值取最新**：按 `(parse_update_at(update_at), int(confluence_version))` 降序取第一个作为该 label 保留的 fact 值（复用 [service.py:830 `parse_update_at`](../backend/reducer/service.py)）。
  - **把冲突排进 review_queue**：新增一条 review item（见 §3）。
  - **卡上打 flag**：追加 `flags` 字符串，如 `"subsection '<sub>' label '<label>' has conflicting values"`。

> 注意：检测**完全确定性、离线、不需 LLM**。不要在这里调用 `self.llm`。

## 3. 新 review item 形状（fact-conflict）
`validate_review_item`（[backend/schemas/validation.py:122-123](../backend/schemas/validation.py)）**只要求** `["queue_id","type","canonical_id","field","detail","options","status"]` 这 7 个键，**不对 `type` 做 enum 限制**——所以新 type 零摩擦，按这 7 键给齐即可（可带额外键如 `near_misses` 那样）：

```jsonc
{
  "queue_id": "RQ-factconflict-<cid>-<stable_short(sub|label)>",
  "type": "fact-conflict",
  "canonical_id": "<cid>",
  "field": "<subsection_name> / <label>",
  "detail": "Subsection '<sub>' label '<label>' has N conflicting values; temporarily kept newest '<chosen>'.",
  "options": [
    "<value> (<page_id>, v<confluence_version>, <update_at>)",
    "..."
  ],
  "status": "open"
}
```
- `queue_id` 用 `stable_short`（[service.py:826](../backend/reducer/service.py)）对 `sub|label` 取 8 位 hash，保证稳定可去重。
- `options` 每个候选值带上 `page_id` / `confluence_version` / `update_at`，让 owner 能判断该信哪个。

把这些 item 和现有 `queue`（来自 `build_card` 返回的第二个元素）一起回流——`build_card` 已经返回 `(card, queue)`，`run()` 里 `review_queue.extend(conflicts)`（[service.py:64-69](../backend/reducer/service.py)）。把 fact-conflict 也塞进这个 `queue` 即可，**无需改 `run()`**。

## 4. 落点（建议最小改动）
- 在 `_subsection_row` 或 `build_card` 里，拿到每个 subsection 的 facts 后做分组检测；
- 让 `build_card` 把 fact-conflict items 追加进它已有的 `queue` 列表（和 config conflict 同一出口）；
- 给 `card["flags"]` 追加冲突描述。
- 不要改 `match_section` / 归属逻辑——本特性**纯加在已匹配 section 的 facts 之上**。

## 5. 测试（必须加）
扩展 `backend/tests/test_reducer_clean.py`（已在改动集里）：
- 构造两个 section，命中同一 canonical 的同一 subsection、同一 `label`、但 `fact_values`/value 不同、`update_at` 不同。
- 断言：① `review_queue` 里有一条 `type=="fact-conflict"`、`options` 含两值且标了 page/version；② 该 label 保留的展示 fact 值 = 最新那条；③ 卡 `flags` 含冲突描述。
- 再加一个"两 section 同 label 同值"的反例，断言**不**产生 fact-conflict（避免误报）。
- 跑测试前若遇 `OSError [Errno 28]`：把 `TMPDIR/TEMP/TMP` 指到 D: 盘再跑（环境坑）。

## 6. opencode 内网移植说明（Ethan 拷进内网）
内网集成版的 reducer 用 LLM `_normalize_section` + `REDUCE_NORMALIZE_SYSTEM` 做归一，但**冲突检测应放在同一个"facts 归一后、按 (subsection,label) 合并"的点**，语义与本规格一致：
- 对每个 (subsection, label) 分组，归一后的 value 若有 >1 个不同 → 排进 review_queue，item 形状同 §3，按 `update_at`/version 选最新作展示值，卡打 flag。
- **同样不许悄悄定一个"对的值"**——必须进队列等人裁决（与外网这份的设计 B 一致）。
- 检测本身保持确定性；只有 value 的"语义等价判定"可借 LLM（可选），但默认按归一后字符串比较即可。

## 7. 硬规则
- 检测确定性、离线、不调 LLM；不改归属/匹配逻辑；不动 `merge_config_field`。
- 冲突**只排队、不裁决**（freeze 闸是人兜底，reducer 不伪造无依据的"正确值"）。
- 回报：reducer diff + 新测试 + `python -m unittest` 通过截图（脱敏）。
