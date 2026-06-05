# OPENCODE: RAGAS + Chroma 快速验证说明

> 目的: 内网没有 Docker 时,用 `uv sync` 安装 Python 依赖,用 Chroma 做本地持久化向量库快速验证;RAGAS 先作为已安装依赖和后续真 judge 接入口。

## 1. 安装

必须使用 Python 3.12。不要用 Python 3.14: RAGAS 的依赖 `scikit-network` 在 Windows + Python 3.14 下会尝试本地编译,容易失败。

```powershell
uv sync --python 3.12
```

确认依赖:

```powershell
uv run python -c "import importlib.metadata as m; import ragas, chromadb; print('ragas', m.version('ragas')); print('chromadb', chromadb.__version__)"
```

当前锁定依赖在 `pyproject.toml` / `uv.lock`:

- `ragas>=0.4.3`
- `chromadb>=1.5.2` 实际锁到 `chromadb==1.5.9`
- `langchain-community<0.4` 是必要兼容 pin;不加这个 pin 时,RAGAS 0.4.3 可能在 import 时找不到旧的 `langchain_community.chat_models.vertexai` 路径。

## 2. 用 Chroma 跑离线 demo

默认 `config.yaml` 用 `JsonVectorStore`。要验证 Chroma,用 `config.chroma.yaml`:

```powershell
uv run python -m backend.pipeline demo --config config.chroma.yaml
uv run python -m backend.pipeline retrieve --config config.chroma.yaml --query "DM plugin default batch_size?"
uv run python -m backend.pipeline answer --config config.chroma.yaml --query "DM plugin default batch_size?"
```

Chroma 数据落在:

```text
outputs/chroma/
```

实现文件:

```text
backend/adapters/store_chroma.py
```

切换方式只改配置:

```yaml
providers:
  store: chroma

store:
  chroma_path: outputs/chroma
```

## 3. 进内网后的推荐顺序

1. 先保持 `providers.store: chroma`,接真 MCP + gpt-5.5,跑小切片确认 map/reduce/answer/eval。
2. 如果内网已有 pgvector/数据库服务,再把 `providers.store` 切到 `pgvector` 并实现 `backend/adapters/store_pgvector.py`。
3. 如果没有数据库服务,继续用 Chroma 做 PoC 验证是可接受的。

## 4. RAGAS 接入点

当前 `outputs/eval_report.json` 已经输出 RAGAS-compatible 字段:

- `faithfulness`
- `answer_relevancy`
- `context_precision`
- `context_recall`

离线 demo 这些字段由 mock/rule-based harness 计算。进内网后,在 gpt-5.5 judge 可用时,把 `backend/eval/metrics.py` 中这些字段替换为 RAGAS 调用。

建议接法:

1. 从 `outputs/eval_report.json.items[*].per_variant[*]` 取:
   - `question`: `item.q`
   - `answer`: `per_variant.answer`
   - `retrieved_contexts`: 用 `per_variant.retrieved` 回查 `outputs/loaded_refs.json` 的 `body_md`
   - `reference`: `item.gold_answer`
2. 用内网 gpt-5.5 配成 RAGAS judge LLM。
3. 先拿 5-10 条人工标注校准 judge,再跑全量 golden。

注意: RAGAS 需要 LLM judge/embedding 配置。不要在代码里硬编码内网地址或 key;通过 `config.yaml` 或环境变量注入。

## 5. 快速故障判断

- `uv sync` 失败且提到 `scikit-network` / MSVC: 检查是否用了 Python 3.14;改用 `uv sync --python 3.12`。
- Chroma 查询为空: 先跑 `load` 或 `demo`,确认 `outputs/chroma/rows.json` 存在。
- Chroma persistent path 报 `table collections already exists`: 删除旧的 `outputs/chroma/` 后重跑 `uv run python -m backend.pipeline demo --config config.chroma.yaml`。这通常是旧数据目录/中断运行留下的本地状态问题。
- 指标看起来过高: 检查 golden 是否来自原文 holdout,不要从卡片或索引 questions 反推。
