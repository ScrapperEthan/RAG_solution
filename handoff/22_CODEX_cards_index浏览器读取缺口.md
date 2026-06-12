# 22 CODEX：cards_index 浏览器读取缺口

## 现状

`backend/web.py` 当前只用 `StaticFiles(directory=frontend_dir, html=True)` 挂载了 `frontend/`。
因此浏览器访问 `/outputs/cards_index.json` 会返回 404，`frontend/cards.html` 无法在不改后端的前提下自动读取仓库里的 `outputs/cards_index.json`。

## Phase 1 前端处理

- `cards.html` 启动时尝试读取 `/outputs/cards_index.json`。
- 读取失败时自动回退到内置脱敏 sample，并明确提示当前处于 sample 模式。
- 页面提供“载入 cards_index.json”文件入口，可直接读取用户选择的真实 `outputs/cards_index.json`。

## 建议后端补充

请由 backend owner 增加一个只读端点，二选一即可：

1. `GET /api/cards`，返回 `outputs/cards_index.json` 的 card 数组。
2. 将 `outputs/` 以只读静态目录挂载到 `/outputs`，至少允许读取 `cards_index.json`。

建议优先 `GET /api/cards`，便于未来做权限、脱敏与分页。端点就绪后，前端可把它加入自动读取候选，不需要更改卡片渲染逻辑。
