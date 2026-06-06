# RAG PoC Live Demo

This is a build-free frontend served by `backend.web`. It includes streaming
Q&A, Golden Set comparison, retrieved evidence, and the evaluation dashboard.

## Run

From the repository root:

```powershell
uv run python -m backend.pipeline demo
uv run python -m backend.web --host 0.0.0.0 --port 8765
```

Open:

```text
http://localhost:8765/
```

Use `--config config.yaml` to run against the intranet adapters and providers.
