# 17 OPENCODE 本轮衔接代码改动记录

本文记录本轮为了把 `rag_solution-kb` 接回真实 confluence MCP / 图片抓取 / 真实 Copilot LLM 运行链路时，**对原来版本额外改动的 3 个文件**：

- `backend/ingest/chunk.py`
- `backend/reducer/canonicals.py`
- `backend/reducer/service.py`

说明原则：

- 这里只记录**我这轮新增/修改**的代码，不重复解释你原本已有逻辑。
- 对比基线是“你前面给我那版代码”。
- 我尽量给出**清晰 before / after diff**，并标明**当前文件中的行号位置**，方便你复查。

---

## 1. `backend/ingest/chunk.py`

### 改动位置

- 当前文件位置：`backend/ingest/chunk.py:14`

### 改动原因

其实 confluence MCP 抓下来的 markdown table，很多行不是严格的：

```md
| a | b |
```

这种两端都带 `|` 的形式。

其实数据里经常是：

```md
a | b | c
```

也就是：

- 只有中间分隔符 `|`
- 不一定首尾都有 `|`

你原本 `TABLE_RE` 太严格，只接受首尾都带 `|` 的行。结果是：

- `collect_table()` 虽然能认出 header + separator
- 但往下收集 data rows 时，`TABLE_RE.match(lines[i])` 失败
- 最终真实页的大表没有被完整吃进结构化 table 流程

### 具体改动

#### Before

```python
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
```

#### After

```python
TABLE_RE = re.compile(r"^\s*\|?.+\|.+\|?.*$")
```

### 影响

- 放宽了 table row 识别
- 允许真实 Confluence 导出的 `a | b | c` 行被当作 table row
- 直接影响：`3725660167` 这类真实页的大表能够继续进入 `parse_table()`，而不是退化成散文 chunk

### 备注

这一改动是**真实输入兼容修复**，不是 topic 逻辑修复。

---

## 2. `backend/reducer/canonicals.py`

### 改动位置

- 当前文件位置：`backend/reducer/canonicals.py:91-99`

### 改动原因

当前 reducer 依赖 keyword table 里的这些字段：

- `topic_class`
- `subsections`

但你原来这版 `normalize_concept()` 在加载 keyword table 时，没有把这两个字段送进 vocabulary。导致后续问题：

- card 上 `topic_class` 丢失或只能靠 fallback 推断
- reducer 里的 subsection 路由没有输入，容易出现 `subsections: []`
- 进一步影响 cards 内容质量

### 具体改动

#### Before

```python
return {
    "canonical_id": canonical_id,
    "canonical_name": canonical_name,
    "aliases": list_value(raw.get("aliases")),
    "module": list_value(raw.get("module")),
    "topic_type": str(raw.get("topic_type") or raw.get("type") or "").strip(),
    "confidence": float_value(raw.get("confidence"), 1.0),
    "note_useful": str(raw.get("note_useful") or raw.get("why_useful") or "").strip(),
    "boundary": str(raw.get("boundary") or raw.get("topic_boundary") or "").strip(),
    "related_pages": list_value(raw.get("related_pages") or raw.get("related_page") or raw.get("source_pages")),
    "review_note": str(raw.get("review_note") or raw.get("review note") or raw.get("notes") or "").strip(),
    "status": str(raw.get("status") or "approved").strip().lower(),
}
```

#### After

```python
return {
    "canonical_id": canonical_id,
    "canonical_name": canonical_name,
    "aliases": list_value(raw.get("aliases")),
    "module": list_value(raw.get("module")),
    "topic_type": str(raw.get("topic_type") or raw.get("type") or "").strip(),
    "topic_class": str(raw.get("topic_class") or raw.get("class") or "").strip(),
    "subsections": list_value(raw.get("subsections") or raw.get("subsection") or raw.get("children")),
    "confidence": float_value(raw.get("confidence"), 1.0),
    "note_useful": str(raw.get("note_useful") or raw.get("why_useful") or "").strip(),
    "boundary": str(raw.get("boundary") or raw.get("topic_boundary") or "").strip(),
    "related_pages": list_value(raw.get("related_pages") or raw.get("related_page") or raw.get("source_pages")),
    "review_note": str(raw.get("review_note") or raw.get("review note") or raw.get("notes") or "").strip(),
    "status": str(raw.get("status") or "approved").strip().lower(),
}
```

### 影响

- keyword table 里的 `topic_class` 终于能被 reducer 正确消费
- keyword table 里的 `subsections` 不再丢失
- 这是本轮 reducer/card 恢复 subsection 内容的关键前置条件之一

### 备注

这不是“策略变更”，只是把 vocabulary loader 补完整。

---

## 3. `backend/reducer/service.py`

### 改动位置

- 当前文件位置：`backend/reducer/service.py:81-101`
- 当前文件位置：`backend/reducer/service.py:678-682`

### 改动原因

问题在于：

- `map` 里的 section 主要是抽取结果
- 很多 downstream 逻辑（尤其 subsection facts / narrative synthesis）还需要原始 `body_md`
- 但当前 `_load_sections()` 没有把 `refs.json` 的原始 section body 带回来

结果会出现：

- `fact_values` 虽然有，但 `body_md` 丢了或不完整
- `is_heading_only_section()` / `narrative_fact_value()` 等逻辑判断失真
- portal / channels 等 subsection 会出现 `facts: []`、`summary: xxx (no extracted facts)` 这种退化

### 具体改动

#### 3.1 `_load_sections()` 增加 ref lookup 回填

#### Before

```python
def _load_sections(self, map_files: List[Path]) -> List[Dict]:
    sections: List[Dict] = []
    for path in map_files:
        page = read_json(path)
        for section in page["sections"]:
            enriched = dict(section)
            enriched.update(
                {
                    "page_id": page["page_id"],
                    "title": page["title"],
                    "source_url": page["source_url"],
                    "confluence_version": page["confluence_version"],
                    "update_at": page["update_at"],
                    "metadata": dict(section.get("metadata") or {}),
                    "fact_values": list(section.get("fact_values") or []),
                }
            )
            sections.append(enriched)
    return sections
```

#### After

```python
def _load_sections(self, map_files: List[Path]) -> List[Dict]:
    ref_lookup = load_ref_lookup(self.outputs_dir / "refs.json")
    sections: List[Dict] = []
    for path in map_files:
        page = read_json(path)
        for section in page["sections"]:
            enriched = dict(section)
            sid = str(section.get("section_id") or f"{page['page_id']}#{(section.get('heading_path') or [''])[-1]}")
            ref = ref_lookup.get(sid, {})
            enriched.update(
                {
                    "page_id": page["page_id"],
                    "title": page["title"],
                    "source_url": page["source_url"],
                    "confluence_version": page["confluence_version"],
                    "update_at": page["update_at"],
                    "section_id": sid,
                    "body_md": ref.get("body_md", section.get("body_md", "")),
                    "metadata": dict(section.get("metadata") or {}),
                    "fact_values": list(section.get("fact_values") or []),
                }
            )
            sections.append(enriched)
    return sections
```

### 解释

这里新增了三件事：

1. 先加载 `refs.json`
2. 用 `section_id` 建立 map section -> ref section 的对齐
3. 把原始 `body_md` 回填到 reducer 里

---

#### 3.2 新增 `load_ref_lookup()` helper

#### Before

无这个函数。

#### After

```python
def load_ref_lookup(path: Path) -> Dict[str, Dict]:
    if not path.exists():
        return {}
    refs = read_json(path)
    return {str(item.get("section_id") or ""): item for item in refs if isinstance(item, dict) and item.get("section_id")}
```

### 影响

- reducer 现在不再只依赖 map 抽取结果
- 它会把 refs 的原始 section body 一起带回来
- 直接改善了：
  - portal subsection facts 为空
  - channels subsection 只能靠弱 summary 拼接
  - `is_heading_only_section()` 误判

### 本轮可见效果

在 `3725660167` 真实页上，这个修复后：

- `MDC Management Portal.json` 的 `UAT Access Right` / `PROD Access Right` facts 恢复出来
- 不再只是挂 keywords，没有值

---

## 4. 这 3 个改动的联动关系

这绝并不是 3 个独立小修，而是一个串联修复：

### 第一步：`chunk.py`

- 让真实 confluence markdown table 能被正确识别

### 第二步：`canonicals.py`

- 让 keyword table 里的 `subsections` / `topic_class` 能真正进入 reducer

### 第三步：`service.py`

- 让 reducer 能重新拿回 refs 的原始 body，而不只是看 map 的抽取结果

如果只改其中一个，效果都不完整：

- 只改 `chunk.py`，reducer 还是可能拿不到完整 body
- 只改 `canonicals.py`，subsection 仍然可能空跑
- 只改 `service.py`，但 table 没切开，也无法拿到结构化事实

---

## 5. 本轮改动总结

### 本轮我对这 3 个文件实际做了什么

- `backend/ingest/chunk.py`
  - 放宽 `TABLE_RE`

- `backend/reducer/canonicals.py`
  - 在 `normalize_concept()` 增加：
    - `topic_class`
    - `subsections`

- `backend/reducer/service.py`
  - 在 `_load_sections()` 增加 `refs.json` 回填
  - 新增 `load_ref_lookup()` helper

### 这些改动属于什么类型

- 不是 topic 策略重写
- 不是业务词表改写
- 不是硬编码某个页面
- 属于“把你已有的新架构，接回真实输入和真实 reducer 数据面”的衔接修复

---

## 6. 后续约定

按你的要求，后续我每次再做代码调整时，会在 `handoff/` 里补一份变更记录，至少包含：

- 改了哪些文件
- 改了哪些函数/正则/配置
- before / after diff
- 为什么改
- 会带动什么下游代码/行为变化

建议后续文件命名延续：

- `18_OPENCODE_xxx.md`
- `19_OPENCODE_xxx.md`

方便你持续沉淀。
