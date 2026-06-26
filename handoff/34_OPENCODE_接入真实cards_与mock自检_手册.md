# 34 OPENCODE/COPILOT 手册：接入真实 cards + 怎么确认自己没在用 mock 卡

**给 opencode / copilot（内网集成版）。claude 在外网定接缝 + 自检标准，opencode 在内网换数据 + 自检后回报。** Ethan 手动把本文件拷进内网。

> 配套：LLM 接入看 [handoff/27](27_OPENCODE_内网copilot集成到LLM_手册.md)（copilot 适配器）。本手册只管 **卡片数据从哪来、怎么换成真实的、怎么一眼确认不是 mock**。

## 0. 一句话任务
前端 demo 做得太真，进内网后**肉眼分不清卡片是 mock 还是真实**。外网已加好「demo 指纹检测 + 大红警示条」。你要做的是：**把 `outputs/cards_index.json` 换成真实卡片，然后跑自检让所有信号都显示 `real`。**

## 1. 卡片数据流（先看懂再动）
```
fixtures/confluence (合成语料)  ─┐
真实 Confluence 切片            ─┴─▶ pipeline: ingest → map → reduce ─▶ outputs/cards_index.json
                                                                              │
                                              GET /api/cards (backend/web.py) ─┘
                                                                              │
                                          前端 index.html / cards.html 读取并渲染
```
- 卡片**唯一真源**是 `outputs/cards_index.json`，由 `reduce` 步写出（`backend/reducer/service.py`）。
- 后端 `GET /api/cards` 原样吐这个文件；`GET /api/health` 顺带报告它是 demo 还是 real。
- **前端不存卡片**，刷新就重新读后端。所以换数据 = 换这个文件 + 重启/重读，不用动前端。

## 2. 什么算「mock 卡」——demo 指纹（单一真源）
判定逻辑在 **`backend/web.py`** 的 `card_is_demo()` / `cards_mode()`，前端 `cards.html` 里镜像了同一份常量。**任意一条命中即判 demo**：

| 指纹 | 常量 | 来自 |
|---|---|---|
| `canonical_id` 以 `C-DEMO` 开头 | `DEMO_CARD_ID_PREFIX` | 前端离线示例卡 |
| 任一 source 的 `page_id` 以 `910000` 开头（即 9100001–9100009） | `DEMO_CARD_PAGE_PREFIX` | 合成语料约定（page id 9100001-3） |
| 任一 source 的 `source_url` 含 `confluence.local` 或 `example.test` | `DEMO_CARD_HOSTS` | fixture / 测试假域名 |

`cards_mode` 三态：`empty`（没卡）/ `demo`（命中任一指纹）/ `real`（一条都没命中）。**保守取向**：哪怕只有一张卡带指纹，整套也判 demo——宁可误报，绝不让半合成语料冒充真实。

## 3. 怎么接入真实 cards
有真实切片就走 A；卡片在别处已生成好就走 B。

### A. 在内网跑 pipeline 产真实卡（推荐）
1. `config.yaml` 切到真实 provider（细节见 handoff/27 / embedder 线）：
   ```yaml
   providers:
     confluence: mcp        # 或你内网真实的 confluence 源（别用 file→fixtures）
     llm: copilot
     embedder: intranet
     store: chroma          # 或 pgvector
   slice:
     root: "<真实空间/页面路径>"
   ```
2. 重新产卡（会重写 `outputs/cards_index.json`）：
   ```bash
   python -m backend.pipeline ingest
   python -m backend.pipeline map
   python -m backend.pipeline reduce   # ← 这一步写出 cards_index.json
   python -m backend.pipeline load     # 建检索库，问答链路需要
   ```
   > ⚠ 不要用 `python -m backend.pipeline demo`——它会 `clean_demo_outputs()` 清空 outputs 再用**合成 fixture** 重建，产的就是 mock 卡。
3. 重启后端（`python -m backend.web`）。前端刷新即读到真实卡。

### B. 直接放入已生成好的真实 `cards_index.json`
把真实文件拷到 `outputs/cards_index.json`（数组结构，schema 见现有文件 / `backend/schemas/validation.py`），重启后端即可。临时排查也可在 `cards.html` 点「载入 cards_index.json」读本地文件。

## 4. 自检：怎么一眼确认「没在用 mock 卡」
换完后，下面**四个信号必须一致指向 real**，任一仍报 demo 就是没换干净：

1. **前端 index.html**：顶部**没有**大红斜纹警示条（`⚠ DEMO / 合成数据 · 非真实内网结果`）。出现即表示 provider 或卡片仍是 demo，条里会写明命中了哪条。
2. **前端 cards.html**：顶部**没有** `⚠ 脱敏 DEMO 卡片` 红条；「数据源」小框显示「N 张真实卡」（绿色），不是黄色 demo 警告。
3. **health 接口**：
   ```bash
   curl -s http://127.0.0.1:8765/api/health | python -m json.tool
   # 期望：  "cards_mode": "real"   （不是 "demo" / "empty"）
   #         "cards_count": <真实张数>
   #         "providers": {"llm":"copilot","embedder":"intranet", ...}  ← 不是 mock/hash
   ```
4. **cards 响应头**（不解析 body 的快查；用 GET dump 头，别用 `-I`/HEAD——该路由只注册 GET）：
   ```bash
   curl -s -D - -o /dev/null http://127.0.0.1:8765/api/cards | grep -i x-cards-mode
   # 期望： x-cards-mode: real
   ```

### 文件级直查（最硬，不依赖服务）
直接 grep 真源文件，命中数必须为 0：
```bash
grep -Eo "confluence\.local|example\.test|\"page_id\": ?\"910000[0-9]\"|C-DEMO" outputs/cards_index.json | sort | uniq -c
# 期望：无输出（0 命中）。任何一行命中 = 还有 mock 卡混在里面。
```

## 5. 验收清单（逐项回报，脱敏）
- **A**. §4 四个信号全 `real`；贴 health JSON（脱敏真实 URL/页 id）+ `x-cards-mode` 头 + grep 0 命中。
- **B**. index.html / cards.html 截图：均**无**红色 demo 警示条。
- **C**. 反向验证（证明检测有效）：临时切回 `demo` 跑一次，确认四信号都翻成 `demo` + 红条出现；再切回真实。
- **D**. mock 回归不破：`python -m unittest discover -s backend/tests` 仍全绿（含新增 `CardsModeTest` / `test_health_flags_demo_cards` / `test_demo_data_is_loudly_flagged_on_both_pages`）。

## 6. 范围 / 红线
- **不要改指纹检测来「让红条消失」**。红条消失的唯一正当方式是换成真实卡。若真实语料合法地命中了某指纹（例：真实 Confluence 页 id 恰好以 `910000` 开头、或真实域名含 `example.test` 子串），那是检测需要收窄——**改 `backend/web.py` 的 `DEMO_CARD_*` 常量（单一真源），并同步 `frontend/cards.html` 里的镜像常量 + 本手册 §2 表格**，外网补测后同步回内网。别在内网私改前端检测让两边分叉（理由同 handoff/27 §5）。
- **outputs/ 不提交**（已在 `.gitignore`）。`cards_index.json` 含真实内网 URL / 人名 / JIRA，**绝不能传出内网**。
- 汇报材料里**叶子值（真实数值/邮箱/人名）要打码**，别拿 mock 数据充真实结果对外汇报。

## 7. 回报物
- §5 验收 A–D 逐项结果（截图 + 命令输出，脱敏）。
- 若动了指纹常量：`web.py` + `cards.html` 的 diff + 收窄理由。
