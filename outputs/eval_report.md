# Eval Report

- Run: `2026-06-05T16:03:38.210248+00:00`
- Metric source: `mock-deterministic`
- Golden size: 15

| Variant | hit@8 | recall@8 | faithfulness | association recall | drill miss rate |
|---|---:|---:|---:|---:|---:|
| body · vector · pure RAG | 0.93 | 0.91 | 0.92 | - | - |
| body · hybrid · pure RAG | 0.87 | 0.83 | 0.88 | - | - |
| questions · vector · pure RAG | 0.93 | 0.93 | 0.92 | - | - |
| questions · hybrid · pure RAG | 0.87 | 0.87 | 0.88 | - | - |
| both · hybrid · pure RAG | 0.87 | 0.87 | 0.88 | - | - |
| both · hybrid · rerank | 1.00 | 0.93 | 0.95 | - | - |
| card direct | 0.53 | 0.49 | 0.72 | 0.97 | 1.00 |
| card route + grounding | 0.93 | 0.86 | 0.92 | 0.97 | 0.00 |
| agentic card + RAG fallback | 0.53 | 0.49 | 0.72 | 0.97 | 1.00 |
