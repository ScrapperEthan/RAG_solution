# Eval Report

- Run: `2026-06-04T15:01:29.510718+00:00`
- Golden size: 15

| Variant | recall@8 | faithfulness | association recall | drill miss rate |
|---|---:|---:|---:|---:|
| body · vector · pure RAG | 0.93 | 0.92 | - | - |
| body · hybrid · pure RAG | 0.73 | 0.82 | - | - |
| questions · vector · pure RAG | 0.80 | 0.86 | - | - |
| questions · hybrid · pure RAG | 0.87 | 0.89 | - | - |
| both · hybrid · pure RAG | 0.87 | 0.89 | - | - |
| both · hybrid · rerank placeholder | 0.87 | 0.89 | - | - |
| card direct | 0.53 | 0.68 | 1.00 | 1.00 |
| card route + grounding | 0.53 | 0.72 | 1.00 | 0.00 |
| agentic card + RAG fallback | 0.53 | 0.72 | 1.00 | 0.57 |
