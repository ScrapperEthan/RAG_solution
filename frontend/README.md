# Evaluation Dashboard

The dashboard is a static frontend. It reads:

```text
../outputs/eval_report.json
```

No Node/npm build step is required.

## Run

From the repository root:

```powershell
uv run python -m backend.pipeline demo
uv run python -m http.server 8765
```

Open:

```text
http://localhost:8765/frontend/
```

Use the `Export` button to print or save the current view as PDF from the browser.
