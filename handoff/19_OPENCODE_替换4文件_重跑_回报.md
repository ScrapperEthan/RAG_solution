# 19 OPENCODE 本轮：替换 4 个文件 → 从 ingest 重跑 → 回报（不要改代码）

claude 在外网 canonical 仓库修了 4 个真 bug（详细 before/after 见 `handoff/18`）。本轮你只做两件事：**替换文件 + 重跑 + 照实回报**。

---

## 1. 替换这 4 个文件（整文件覆盖内网 `rag_solution-kb` 对应路径）

- `backend/reducer/canonicals.py`
- `backend/util.py`
- `backend/ingest/chunk.py`
- `backend/reducer/service.py`

> 这 4 个文件已经把你上轮 `handoff/17` 的 3 个补丁（TABLE_RE / normalize_concept / body_md 回填）都包含进去了，是叠加在你那版之上的更全版本，**直接覆盖即可**，不用再手动 merge。

## 2. 从 `ingest` 重跑整条链

必须从 ingest 开始（不是只重 reduce）——section_id 是在 chunk 阶段写进 refs 的，只重 reduce 不会生效：

```
ingest → map → discover → reduce
```

## 3. 跑完照实回报下面几样（原样贴回，**不要判断对错、不要为了好看去改代码**）

1. 四个 step 命令行打印的那行 JSON（ingest / map / discover / reduce 各一行 `{...}`）。
2. 重新跑一遍 `diag_chunk.py`，**整段输出**贴回来。
3. `outputs/cards/` 下的**文件名列表 + 数量**（只要文件名，不要卡片全文）。
4. 任选一张卡，贴它的 `subsections` 字段：每个 subsection 的 `name` + 它 `facts` 里的 `label`/`tier`/`value`（URL 可以留）。
5. 跑的过程里任何报错/异常，**原样**贴回来（traceback 全文）。

## 4. 硬规则（重要，请严格遵守）

- **不要修改**这 4 个文件、也不要改 backend 里任何代码。看到结果不对，**照实汇报**就好——由 claude 在外网改完你再同步，不要自己动手修。
- 如果**实在跑不起来、非改不可**（例如缺字段直接崩溃），允许你做**最小**改动让它能跑，但必须在新文件 `handoff/20_OPENCODE_xxx.md` 写清楚：改了哪个文件、哪个函数/正则/行、before/after、为什么改、会带动什么下游变化——一行都不能省。
- 回报时**不要**大段粘贴内网真实数据（整页正文、整批 URL、人名）；只贴结构、计数、必要的小片段即可。

---

回报后由 claude 判断：①卡片数量是否对 ②section_id 是否还碰撞 ③anchor 是否还带表头 ④channels 卡各渠道叙述是否串台。这些判断**由 claude 做**，你只负责把现象贴清楚。
