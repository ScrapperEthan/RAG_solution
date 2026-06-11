# 18 CLAUDE 本轮修复记录（矩阵路由 / section_id 唯一化 / 表头污染 / 词表字段）

承接 `handoff/17`（opencode 内网 3 补丁）。本轮在**外网 canonical 仓库**修了 4 个真 bug，全部跑通 27 个离线回归测试。
**内网请用这 4 个文件直接替换，然后从 `ingest` 重跑**（section_id 是 chunk 阶段写进 refs 的，必须重 ingest）。

改动文件：
- `backend/reducer/canonicals.py`
- `backend/util.py`
- `backend/ingest/chunk.py`
- `backend/reducer/service.py`

---

## 1. `backend/reducer/canonicals.py` — normalize_concept 补 topic_class / subsections

= 同步 handoff/17 §2（外网这份之前还是旧版）。在 `normalize_concept()` 返回 dict 里加：

```python
"topic_class": str(raw.get("topic_class") or raw.get("class") or "").strip(),
"subsections": list_value(raw.get("subsections") or raw.get("subsection") or raw.get("children")),
```

不补这个，冻结词表里的 subsections/topic_class 会在 `load_vocabulary` 这道被丢掉。

---

## 2. `backend/util.py` — section_id 用完整 heading_path（修矩阵 cell 碰撞）

### 原因
diag 实测：61 个矩阵 cell，但 `section_id` 只取 leaf=attribute → 11 个 id 互撞（`#Information` ×5：PN/SMS/Email/Letter/Whatsapp 五渠道的 Information cell 塌成同一个 id）。
opencode 的 `load_ref_lookup` 按 section_id 建 dict 后写覆盖前写 → 纯叙述矩阵 cell 的 body_md 回填会**串到别的渠道**。

### Before
```python
def section_id(page_id: str, heading_path: List[str]) -> str:
    heading = heading_path[-1] if heading_path else ""
    return f"{page_id}#{heading}"
```

### After
```python
def section_id(page_id: str, heading_path: List[str]) -> str:
    parts = [str(part).strip() for part in (heading_path or []) if str(part).strip()]
    tail = parts[1:] if len(parts) > 1 else parts
    return f"{page_id}#{' > '.join(tail)}"
```

矩阵 cell 的 heading_path 含 channel+attribute → id 天然唯一。

---

## 3. `backend/ingest/chunk.py` — 两处

### 3.0 放宽 TABLE_RE（= 同步 handoff/17 §1，**首轮漏折了**，会导致表全部不解析）
真实 Confluence→Markdown 的表行常**不带首尾 `|`**（`a | b | c`）。严格版只认 `|...|`，`collect_table` 收 0 行 → 矩阵/记录表全退化成散文/qa（症状：diag `matrix cells: 0`、卡 subsections 全空）。

```python
# Before（严格，漏掉真实无包裹行）
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
# After（放宽：首尾 | 可选，至少一个内部 |）
TABLE_RE = re.compile(r"^\s*\|?.+\|.+\|?.*$")
```

### 3.1 表头行被当成 markdown 标题（修 heading_path 污染）

### 原因
diag 实测 30 个 section 的 heading_path 被 `|` 污染，样例：
`heading_path = ['MDC Project Check List', '| Use Case ID | Use Case Name | ... | Letter']`
真实 Confluence→Markdown 把一行表头渲染成了 `##` 标题，于是整页内容挂在这个假标题下，污染所有子节点的 anchor/section_id。

### 改动（parse_page 主循环里 HEADING 分支）
标题文本里带 `|` 的，不当成标题——去掉 `#` 标记，让表格/散文逻辑接管这一行：

```python
heading = HEADING_RE.match(line)
if heading and "|" not in heading.group(2):
    flush_prose()
    ...原有 h2/h3 赋值...
    i += 1
    continue
if heading:
    line = heading.group(2)   # 去掉假标题的 # 标记
    lines[i] = line           # 让后面的 is_table_start / 散文逻辑处理
```

附带好处：如果那张表后面跟着分隔行，它现在能被真正解析成结构化表，而不是漏成标题。

---

## 4. `backend/reducer/service.py` — 4 处

### 4.1 canonical_ids_from_metadata：矩阵 cell 路由到「行 topic + 列 topic」（修 7 topic→5 card）

#### 原因
winner-take-all 评分：每个矩阵 cell 的 channel 命中 C-0001 的 subsection 得 4 分，attribute 命中别的 topic 的 alias 只得 3 分；`top=max` 只留 C-0001 → 全部 61 个 cell 都塞进 C-0001，**attribute 定义的 topic（C-0005 模板治理、C-0006 测试/退信）一个 cell 都拿不到 → 不出卡**。所以 7 个 approved topic 只出了 5 张卡。

#### Before（评分 + 取 top）
```python
scored = []
for cid, canonical in canonicals.items():
    score = 0
    if canonical_id_in_text(signal_text, {cid: canonical}): score += 3
    sub_terms = [...]
    if any(term in sub_terms for term in row_terms): score += 4
    if score > 0: scored.append((score, cid))
top = max(score for score, _ in scored)
return [cid for score, cid in scored if score == top]
```

#### After（行 topic ∪ 列 topic，不再 winner-take-all）
```python
row_terms = [normalize_term(metadata[k]) for k in ("channel", "row_key") if metadata.get(k)]
column_text = " ".join(metadata.get(k, "") for k in ("attribute", "question")).strip()
ids = []
for cid, canonical in canonicals.items():
    sub_terms = [normalize_term(s) for s in canonical.get("subsections", []) if s.strip()]
    if any(term in sub_terms for term in row_terms):      # 行 topic：cell 的行键是该 topic 的 subsection
        ids.append(cid); continue
    if column_text and canonical_id_in_text(column_text, {cid: canonical}):  # 列 topic：attribute 命中该 topic 名/别名
        ids.append(cid)
return dedupe_strings(ids)
```
注：列匹配只看 `attribute`/`question`，**不看 heading_path**，避免被 #3 的表头污染干扰。

### 4.2 _load_sections：从 refs.json 按 section_id 回填 body_md（= 同步 handoff/17 §3）
与 17 §3 一致；配合 #2 唯一 section_id 后，回填不再串台。

### 4.3 新增 `load_ref_lookup(path)` helper（= 17 §3）。

### 4.4 reducer 内部 `section_id(section)` 的 fallback 改用 `util.section_id`，与 chunk 同一格式对齐。

---

## 验收
- 27 个离线回归全过（含新增 `test_canonicals_seam.py`、`test_reducer_clean.test_matrix_cell_routes_to_row_and_column_topics`、`test_chunk_general.test_pipe_heading_does_not_pollute_heading_path`）。
- 内网重跑后应看到：①7 张卡（C-0005/C-0006 出现）②section_id 不再碰撞 ③anchor 不再带 `| Use Case ID |...` ④channels 卡叙述 facts 不串台。
