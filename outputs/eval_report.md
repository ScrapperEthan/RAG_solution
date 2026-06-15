# Eval Report

- Run: `2026-06-15T07:00:31.106495+00:00`
- Metric source: `mock-deterministic`
- Golden size: 15

| Variant | hit@8 | recall@8 | faithfulness | association recall | drill miss rate |
|---|---:|---:|---:|---:|---:|
| body · vector · pure RAG | 0.93 | 0.90 | 0.92 | - | - |
| body · hybrid · pure RAG | 0.67 | 0.67 | 0.78 | - | - |
| questions · vector · pure RAG | 0.60 | 0.60 | 0.75 | - | - |
| questions · hybrid · pure RAG | 0.67 | 0.67 | 0.78 | - | - |
| both · hybrid · pure RAG | 0.67 | 0.67 | 0.78 | - | - |
| both · hybrid · rerank | 0.87 | 0.87 | 0.88 | - | - |
| card direct | 0.27 | 0.27 | 0.58 | 0.00 | 1.00 |
| card route + grounding | 0.40 | 0.40 | 0.65 | 0.00 | 0.00 |
| agentic card + RAG fallback | 0.27 | 0.27 | 0.58 | 0.00 | 1.00 |
