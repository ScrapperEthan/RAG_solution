# 28 修复回报：agentic drilldown 取不到 refs（section_id 格式不匹配）— 已在外网修复

**opencode 在内网报的问题（in.txt），claude 已在外网修好并 push。Ethan 同步进内网后，opencode 按 §3 复测。**

## 1. opencode 的定位完全正确
`backend/agentic/service.py` 的 `refs_for_card()` 用
`heading = source["anchor"].split(" > ")[-1]` + `f"{page_id}#{heading}"`
拼 section_id，但 `loaded_refs.json` 的真实 key 是**完整 heading 路径**形式
（`backend/util.py::section_id` = `page_id#<heading_path[1:] 用 " > " 连接>`）。

外网真实数据已核对（synthetic demo 同构）：
- loaded_refs key：`9100001#MDC supported notification channels > PN > Delivery Mode`
- 旧代码拼出：`9100001#Delivery Mode`（只取末级，且 `anchor` 还带页标题前缀 `MDC Project Check List > ...`，双重错）
- → 永远对不上 → `refs_for_card()` 返回 **0 refs** → `answer_from_refs` 收到空 context → **NO_ANSWER**。

**同一个 bug 在 `backend/load/service.py::build_descriptions` 又出现一次**（`f"{page}#{heading_path[-1]}"`），导致 descriptions 检索索引被饿死（demo 上只建 36 条），这也是 **pure-rag 质量"一般"** 的一个原因。

## 2. claude 已做的修复（外网, commit 见 git log）
- **`refs_for_card()` 改用 `source_section_ids`**：卡片 fields / subsections / facts 里记录的 `source_section_ids` **本就等于 loaded_refs 的 key**（已核对一字不差）。直接拿它查，不再从 anchor 反推。并**纳入 subsections（卡片的大部分证据在这里）**，specific(子项)优先、field 聚合兜底。
  - 效果（demo 7 张卡）：每张卡 drilldown 从 **0 → 3~8 refs**。
- **`build_descriptions` 改用完整 section_id**：descriptions **36 → 218**（demo），恢复 questions/summary 检索面。
- **可观测性（直接回应"看不到问题在哪"）**：当源下钻/检索命中 0 条原文时——
  - 后端 `logger.warning(...)`（输出到 server stderr）；
  - `execution.steps` 追加一条 **`⚠ 命中 0 条原文证据：未取到可引用来源段落，因此返回 NO_ANSWER`**（前端执行轨迹已会渲染 steps，所以会显示）；
  - 结果加 `diagnostic` 字段。
- **回归测试**：`backend/tests/test_agentic_drilldown.py`（锁住"用完整 section_id 解析、leaf-only key 解析不到、空证据触发 diagnostic"）。全套 **98 tests OK**。

## 3. opencode 在内网要做的（Ethan 同步后）
1. `git pull` 取这次修复。
2. **重跑流水线到 `load`**（理想是 `ingest→map→reduce→load` 全跑）：`refs_for_card` 的修复对**现有 cards 立即生效**，但 **descriptions 的修复必须重跑 `load`** 才能再生 `loaded_descriptions`。
3. 复测之前 NO_ANSWER 的 Golden（MDC-GS-001 / 004 / 010）在 **agentic** 与 **卡片+回原文取证(card-grounding)** 下：应当返回**有据可查的答案**，不再是 NO_ANSWER。
4. 若仍 NO_ANSWER：看执行轨迹的 `⚠ 命中 0 条原文证据` + server 日志的 warning，**回报是哪张卡 / 哪些 section_id 没解析到**（带脱敏样例），claude 继续查。

## 4. 验收标准
- agentic 下 exact 类问题（UAT/Prod 登录链接、channels 等）能回**带 citation 的真实答案**。
- 真正无来源时才出现 `diagnostic`/`⚠` 步骤；有来源时不出现。
- `load` 的 descriptions 数远高于修复前（demo 36→218 量级）。

## 5. 已知的次级问题（本次未改，单列）
opencode 也指出：`answer_from_card()`（**卡片直答**）只从 `card["fields"]` 取值、**几乎不用 subsections**，而很多卡的关键细节在 subsections——所以即便 card-direct 走通，"直答"也偏弱（且它**不调 LLM、是确定性拼字段值**，这就是你看到"直接把卡片内容原文拿过来"的原因）。
- 本次的 drilldown 修复已让 **agentic/卡片+取证** 路径把富证据的问题导向"回原文重新生成"，基本满足"看完原文再答"的诉求。
- 若还要增强 card-direct 本身（让它也吃 subsections，或改成"把卡片喂给 LLM 读完再答"），那是**第二层、单独一轮**，需要时再开规格。

## 6. 追加修复：LLM 回答"漏 channel"= drilldown 截断（已修）
内网现象：问"MDC support 有哪些 channel"，应有 PN/SMS/Email/Letter/WhatsApp/WeChat，但 LLM 只答 2~3 个。**根因不是 LLM 漏读，是喂给它的原文不全**：`refs_for_card` 之前 `return refs[:8]`，而 channels 卡是矩阵（6 渠道 × 数个属性 ≈ 16~32 段），截到 8 段只覆盖前 2~3 个渠道，后面的渠道**根本没进 LLM 的 context**，所以它如实只答看到的那几个。
- **修法**：cap 从 8 提到 `MAX_DRILLDOWN_REFS = 40`（矩阵格很小、单卡段数有界，token 安全）。验证：demo 的 channels 卡 drilldown 由 8 → **16，5 个渠道全部到达 LLM**。
- 注意 **pure-rag 同样受 `retrieval.top_k`(默认 8) 限制**——枚举类问题（"列出所有 X"）走 pure-rag 也会漏，可在 `config.yaml` 调高 top_k；但卡片取证路径（已修）对"整卡枚举"更合适，因为它把整张卡的段落都给 LLM。

## 7. 用 Debug 模式自查（codex 已实现，fb75882）
前端勾选 **Debug 模式**（带 `debug:true`），回答后看链路面板，逐跳验证：
1. **routing**：命中哪张卡、LLM 选的还是关键词兜底。
2. **drilldown.counts**：`gathered`(收集) / `resolved`(命中) / `missed`(未命中) / **`capped_to`**(实际喂给 LLM 的条数)。
   - `missed` 非空 → 还有 section_id 对不上 loaded_refs（再报 claude）。
   - `gathered > capped_to` → 仍被截断（说明该卡段数 > 40，需再调 cap 或换枚举策略）。
3. **refs_used[].body_md**：确认"含答案的原文段落"确实在里面（如所有渠道的 cell）。
对"MDC support 有哪些 channel"：复测应看到 `resolved` 含全部渠道的 cell、`capped_to` ≥ 渠道数、答案列全。**若仍漏，把该问题的 `debug` JSON（脱敏）回报，claude 据此继续。**
