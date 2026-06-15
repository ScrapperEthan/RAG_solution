# 25 CODEX 前端规格：社区图可视化（cards.html「知识地图」）

**给 codex（外网仓库 `frontend/`）。claude 写规格，codex 实现，claude review。**

> 灵感来自 `llm-wiki-agent` 的 `graph.html`（vis.js + Louvain 社区）。我们做一个**纯展示层**的"知识地图"，给领导/业务一眼看清"卡片之间怎么聚成几块"。**纯展示，不改任何后端、不改 reduce。**

## 0. 与 23 号的关系（顺序）
本规格**叠加在 `cards.html` 上**，是 Card Explorer 的一个新视图。**请在 `handoff/23`（前端澄清 pass）落地并通过后再做本规格**，避免同文件改动撞车。本规格只**新增**一个图视图，不改 23 改过的部分。

## 1. 现状（复用，别重写）
- `cards.html` 是自包含单文件（内联 JS/CSS + `style.css`），已从 `GET /api/cards` 读 `cards_index.json`，无数据回退脱敏 `SAMPLE_CARD`（[cards.html:328-364](../frontend/cards.html)）。
- 已有 `state.cards` / `state.selectedId` / `selectedCard()` / `renderCardDetail()`——**图视图点节点就复用这些**去选中并展开右栏那张卡。
- **硬约束**：纯静态、**无打包工具、无框架**、复用 `style.css` 的 CSS 变量。内网会拦 CDN，所以**不要外链 vis.js/d3**——用 vanilla `<canvas>` 或 SVG 自己画力导向图。

## 2. 数据（已够用，无需后端改动）
每张卡（`cards_index.json` 元素）里可直接取：
- 节点：`canonical_id`（id）、`canonical_name`（label）、`module`（数组，用于分组/兜底着色）、`topic_class`、`status`。
- **边**：`fields[]` 里 `field=="related_components"` 的那条带 `soft_links: [canonical_id, ...]`（由 [backend/reducer/service.py:539-559](../backend/reducer/service.py) `related_components_field` 产出，指向**其它卡**的 canonical_id）。每个 `soft_link` → 一条无向边（去重）。
- 可选次级边：同 `module` 互连（淡边），帮助没有 soft_links 的孤点也能聚类——**默认关，做成可勾选开关**，避免图太密。

> 若某卡没有 `related_components` 字段就没有显式边，属正常；用 module 兜底分组着色，别报错。

## 3. 交付物
- 在 `cards.html` 顶部操作区加一个**视图切换**：`结构 / 知识地图`（默认"结构"=现状）。切到"知识地图"时，把 `.workspace`（或在其上方/替换）渲染成图。
- 图：vanilla **canvas 或 SVG 力导向**（简单的 Fruchterman-Reingold / 朴素弹簧-斥力迭代即可，节点数是个位到几十，性能无压力）。
- **社区着色**：实现一个**极简 Louvain/标签传播**（vanilla，几十行）给节点分社区上色；**实现不了或图太稀疏时，回退按 `module` 着色**（用 `moduleKey(card)` 一致分组）。两种都给图例。
- **离线**：无 `/api/cards`/无数据时，用现有 `SAMPLE_CARD`（必要时 codex 再内置 2~3 张脱敏卡 + 几条 soft_links）也能渲染一张小图，**不准硬编码任何真实内网数据**。

## 4. 交互
- 节点：圆点 + 短 label（`canonical_name`，超长截断）；按社区/module 上色；大小可按"边数(度)"略缩放。
- **点节点** → `state.selectedId = 该 id`，切回"结构"视图并 `renderCardDetail()` 展开那张卡（复用现有逻辑）。
- hover → tooltip：`canonical_name` + `module` + 度数。
- 图例：每个社区/module 一个色块 + 名称。
- 空/错误态：无边时显示散点 + 提示"这些卡之间暂无 related_components 关联"。
- 移动端：能渲染、可缩放或单列回退即可，不追求完美。

## 5. 验收清单
- [ ] "知识地图"视图能从 `/api/cards` 的卡渲染节点；soft_links 渲染成无向边（去重）。
- [ ] 节点按社区（或 module 兜底）着色，有图例。
- [ ] 点节点能选中并在"结构"视图展开对应卡（复用 `state.selectedId`/`renderCardDetail`）。
- [ ] 无后端/无数据时用脱敏 sample 渲染小图，不报错。
- [ ] 纯 vanilla、无 CDN/无打包工具、复用 `style.css`；"结构"视图原功能不受影响。

## 6. 硬规则
- **纯展示层**，不改 backend、不改 reduce、不改 23 号已落地的澄清部分。
- 不外链任何第三方库（内网拦 CDN）；社区检测/力导向都用 vanilla 自实现。
- 回报：`cards.html` diff + 知识地图截图（脱敏 sample，不贴真实内网数据）。
