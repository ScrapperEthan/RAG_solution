# RAG PoC — Implementation Spec (Confluence → pgvector)

> Handoff spec for opencode. Written in English because the artifacts (Confluence body, prompts, SQL, eval) are English; question/summary generation and the system are **multilingual (EN + ZH)** by default. Ping me to flip the narrative to Chinese if reviewers prefer.

---

## 1. Goal & philosophy

Build a **measurement-driven RAG PoC** over the department's Confluence pages. The PoC's real deliverable is **not** a finished pipeline — it is an **evaluation harness + a small set of comparable variants** that tells us which retrieval design actually works on our content, so we can scale the winner.

Design rule: **automate first, curate later.** Do not hand-restructure Confluence up front. Capture existing structure, enrich it with the internal LLM, measure, and only invest human curation where measurement shows a gap.

Three logical layers (all derived automatically in the PoC):

| Layer | What it is | Role |
|---|---|---|
| **metadata** (a.k.a. "Wiki LLM/Spec") | type/facet tags on each chunk | pre-filter before search |
| **description** | 3–7 generated questions + 1 summary per chunk | **retrieval index** (hypothetical-question indexing) |
| **reference** | the real content chunk | what gets returned / fed to the LLM |

Plus a light **page-level summary node** to catch multi-hop questions ("how do X and Y work together").

---

## 2. Scope (PoC slice)

- **In scope:** one vertical slice — `06-Delivery / 10. Planned Project / 2026 Planned Project` (and its descendants).
- **Out of scope (PoC):** full Confluence ingestion; multimodal/image embedding; ANN index tuning; production auth/serving.
- Keep the slice small enough that **exact (brute-force) vector search** is viable — that removes ANN recall as a confounding variable.

---

## 3. Pipeline overview

```
MCP capture ─► parse & chunk ─► enrich ─► load (pgvector) ─► retrieve ─► answer ─► evaluate
   (pages)      (sections)     (Q's,      (refs +            (filter →   (gpt-5.5   (RAGAS +
                               summary,    descriptions +     hybrid →    + cites)    matrix sweep)
                               captions)   summaries)         rerank)
```

---

## 4. Ingestion (capture)

MCP returns, per page: `title, source_type, confluence_space, confluence_page_id, source_url, owner, labels, captured_at, update_at, confluence_version`, then the **Markdown body** (title + paragraphs; tables in Markdown; images referenced by local paths).

Ingestion tasks:

1. **Pull the slice subtree** via the Confluence MCP (page list + hierarchy + body).
2. **Extract `tree_path`** (the ancestor chain, e.g. `06-Delivery/10. Planned Project/2026 Planned Project`). It currently sits between the title and the body — parse it out into its own field; do **not** leave it inside `body_md`.
3. Keep `body_md` as Markdown. Record image local paths separately (see §5 image handling).
4. Persist a raw capture artifact (one JSON per page) before chunking, so re-chunking doesn't require re-fetching.

---

## 5. Chunking (reference)

Granularity = **section by Markdown headings `##` (H2) / `###` (H3)**. Build the heading tree; each deepest heading + its body = one candidate reference. Carry the full `heading_path` (`H1 > H2 > H3`) on the chunk.

Rules (do **not** "split on every `##`" naively):

- **Never split** a Markdown table, code block, or list across chunks.
- **Merge up** sections smaller than `min_merge_tokens` (default 100) into their parent.
- **Secondary split** sections larger than `max_tokens` (default 1000) at paragraph boundaries with `overlap_tokens` (default 50).
- **Target** 200–800 tokens per chunk.
- **Fallbacks:** preamble before the first heading, and pages with no headings → split by paragraph/length.

**Tables:** keep the Markdown table intact inside the chunk; set `has_table=true`. Optionally feed a one-line table description into the question generator.

**Images:** PoC does **not** embed images. For each image, use the internal LLM to generate a one-sentence caption from surrounding text, inline it into `body_md` (so it's searchable), keep the local path in metadata, set `has_image=true`.

Fields produced per chunk: `page_id, space, source_url, title, heading_path, tree_path, owner, labels, content_type, component, status, has_table, has_image, body_md, confluence_version, update_at, captured_at`.

---

## 6. Enrichment (LLM = internal gpt-5.5)

### 6.1 Question + summary generation (per reference)

Generate **3–7 questions** the chunk answers, plus a **one-line summary**, **bilingual (EN + ZH)**.

```
SYSTEM:
You generate retrieval questions for a documentation chunk. Given the chunk
(with its heading path), produce 3–7 DISTINCT questions that (a) a real user could
ask and (b) THIS chunk fully answers. Vary phrasing: include at least one keyword-style
and one natural-sentence form. Include exact identifiers (plugin/API/error names) where
present. Never ask something the chunk does not answer. Also write a one-line summary.

Output strict JSON:
{
  "questions_en": [...], "questions_zh": [...],
  "summary_en": "...",   "summary_zh": "..."
}

heading_path: {heading_path}
chunk:
{body_md}
```

### 6.2 Page-level summary node (multi-hop)

One per page. Synthesizes how the page's parts relate; carries its own 2–4 cross-cutting questions, bilingual.

```
SYSTEM:
Summarize this Confluence page into ONE synthesis paragraph capturing how its parts
relate (used to answer cross-cutting questions like "how do X and Y work together").
Then write 2–4 cross-cutting questions the whole page answers. Bilingual EN + ZH.
Output JSON: {"summary_en","summary_zh","questions_en","questions_zh"}.

page title: {title}   tree_path: {tree_path}
page content:
{full_page_md}
```

### 6.3 Metadata enrichment

- `content_type`: bootstrap from `labels` where they exist; fill gaps with an LLM classification into a **small controlled vocabulary** — `what-is | how-to | config | troubleshoot | reference | decision | meeting-notes`. (Adjust the vocab after sampling real pages.)
- `component`: domain facet derived from content (e.g. `DM | journey | adaptor | common | ...`). **Derive the actual value set from a sample of the slice** — do not assume the other department's `common/aOS/iOS`.
- **Facet validation:** before committing facets, take ~20–50 real user questions and check which facet would actually narrow the search. Keep facets that get used; drop the rest.

---

## 7. Database schema (pgvector / Postgres)

Postgres carries everything: vectors (`pgvector`), keyword search (native `tsvector` FTS), and metadata filtering (SQL `WHERE`). Hybrid search = vector ⊕ FTS fused by **RRF**.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- 7.1 references: the real content chunks
CREATE TABLE refs (
  ref_id              BIGSERIAL PRIMARY KEY,
  page_id             TEXT NOT NULL,
  space               TEXT,
  source_url          TEXT,
  title               TEXT,
  heading_path        TEXT,                 -- 'H1 > H2 > H3'
  tree_path           TEXT,                 -- ancestor chain
  owner               TEXT,
  labels              TEXT[],
  content_type        TEXT,                 -- controlled vocab (§6.3)
  component           TEXT,                 -- domain facet (§6.3)
  status              TEXT,
  has_table           BOOLEAN DEFAULT FALSE,
  has_image           BOOLEAN DEFAULT FALSE,
  body_md             TEXT NOT NULL,        -- chunk content (tables + image captions inline)
  body_embedding      vector(1024),         -- for index ∈ {body, both}
  body_tsv            tsvector,             -- for hybrid keyword search
  confluence_version  INT,
  update_at           TIMESTAMPTZ,
  captured_at         TIMESTAMPTZ
);

-- 7.2 descriptions: generated questions (hypothetical-question index), many-to-one to refs
CREATE TABLE descriptions (
  desc_id     BIGSERIAL PRIMARY KEY,
  ref_id      BIGINT REFERENCES refs(ref_id) ON DELETE CASCADE,
  kind        TEXT,            -- 'question' | 'summary'
  lang        TEXT,            -- 'en' | 'zh'
  text        TEXT NOT NULL,
  embedding   vector(1024)     -- for index ∈ {questions, both}
);

-- 7.3 page-level summary nodes (multi-hop)
CREATE TABLE summaries (
  sum_id      BIGSERIAL PRIMARY KEY,
  page_id     TEXT NOT NULL,
  tree_path   TEXT,
  text        TEXT NOT NULL,
  embedding   vector(1024),
  text_tsv    tsvector
);

-- FTS indexes
CREATE INDEX ON refs USING GIN (body_tsv);
CREATE INDEX ON summaries USING GIN (text_tsv);
-- Metadata filter helpers
CREATE INDEX ON refs (content_type);
CREATE INDEX ON refs (component);
CREATE INDEX ON refs (tree_path);
-- Vector index: SKIP for the PoC slice (exact search). Add HNSW only when scaling.
```

Notes:
- **Embedding dim** must match the chosen model. `pgvector` indexed columns historically cap at 2000 dims — if a model exceeds that, switch the column type to `halfvec`. The default model (§8) is 1024-dim, well under the cap.
- `body_tsv` / `text_tsv` populated via `to_tsvector('simple', ...)` (use `'simple'` so exact identifiers aren't stemmed away; revisit per query language).

---

## 8. Embedding (pluggable)

Embedding is **config-injected**, not hard-coded — opencode codes against an interface so the model can be swapped without touching the pipeline.

```python
class Embedder(Protocol):
    def embed(self, texts: list[str], *, kind: str) -> list[list[float]]: ...
    # kind ∈ {"query","passage"} for models that use asymmetric prefixes
```

- **Default (confirmed): multilingual, privately deployable** — `BGE-m3` (1024-dim) or `multilingual-e5-large`. Final pick is TBD; the interface makes it a config change.
- Because users may query in **Chinese against English docs**, multilingual is mandatory and questions are generated **bilingually** (§6.1) so cross-lingual recall doesn't degrade.

---

## 9. Retrieval pipeline

```
query
  └─► (optional) metadata pre-filter  → SQL WHERE on content_type/component/tree_path/...
  └─► VECTOR search
        • index=descriptions → search descriptions.embedding → map desc → ref_id
        • index=body      → search refs.body_embedding
        • index=both      → search both, pool
        • always also search summaries.embedding (multi-hop)
  └─► KEYWORD search (only if search=hybrid)
        • refs.body_tsv @@ plainto_tsquery(query); summaries.text_tsv
  └─► DEDUP to unique ref_id (best rank wins; summary hits expand to their page's refs)
  └─► FUSE lists via RRF:  score(ref) = Σ_lists 1 / (rrf_k + rank)     # rrf_k default 60
  └─► (optional) RERANK with a cross-encoder over (query, ref.body_md)
  └─► top_k refs (default 8) → context
        └─► ANSWER: gpt-5.5, must cite source_url of every ref used; if no
            supporting context, answer "no answer found" (do not fabricate).
```

---

## 10. Variant matrix (what we compare)

Dimensions: `index ∈ {body, questions, both}` × `search ∈ {vector, hybrid}` × `rerank ∈ {off, on}`. Don't run the full 12-cell grid — run this **ladder** and keep everything else fixed:

| ID | index | search | rerank | purpose |
|----|-------|--------|--------|---------|
| V1 | body | vector | off | baseline |
| V2 | body | hybrid | off | does keyword help? |
| V3 | questions | vector | off | does HQ-indexing help? |
| V4 | questions | hybrid | off | HQ + keyword |
| V5 | both | hybrid | off | combined index |
| V6 | both | hybrid | on | + reranker (top of ladder) |

Promote the best cell; toggle one dimension at a time to attribute the gain.

---

## 11. Evaluation

### 11.1 Golden set (LLM-generated — with a hard guardrail)

**Critical:** generate eval questions with a **different prompt and a different view** than the index questions (§6.1). If you reuse the §6.1 style/chunks, retrieval scores are inflated — you'd be testing "can you find the chunk you wrote the question from."

- 30–50 questions, **bilingual**, written in **realistic end-user voice** (terse, keyword-y, sometimes vague), not polished "what is X".
- Cover types: `single | multihop | identifier-lookup | out-of-scope`.
  - `multihop` → gold = **multiple** section ids (tests summary nodes).
  - `out-of-scope` → gold = `NO_ANSWER` (tests precision + refusal).
- Gold labels per item: answering `page/section id(s)` (for recall@k) + a reference answer (for faithfulness).
- **Human spot-check ~20%** of items: is the question realistic and is the gold section actually correct/answerable? Unchecked LLM gold = noisy metric.
- **Freeze** the set; every variant runs the identical set.

```
SYSTEM:
You write realistic questions to TEST a documentation search system. Write as a busy
engineer would actually type — terse, keyword-y, sometimes vague — NOT polished prose,
and DO NOT imitate the indexed questions' style. For each item output:
{ "q_en","q_zh","type"(single|multihop|identifier-lookup|out-of-scope),
  "gold_section_ids":[...] or "NO_ANSWER", "gold_answer":"..." }
Source material (whole page, held out from per-chunk indexing):
{full_page_md}
```

### 11.2 Metrics & tooling

- **Retrieval:** `recall@k` (k = 5, 8), `MRR`, `nDCG@k`.
- **End-to-end:** `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`.
- **Tools:** **RAGAS** for the RAG metrics (maps directly to the above); **promptfoo** or **DeepEval** to sweep the variant matrix and produce a comparison report. All run offline.
- **LLM-as-judge:** judge = gpt-5.5. **Calibrate the judge** against ~10 human-labeled items before trusting scores — guard against a biased judge.

---

## 12. Sample config

```yaml
slice:
  root: "06-Delivery/10. Planned Project/2026 Planned Project"

embedding:
  provider: internal
  model: bge-m3            # multilingual default; swap here
  dim: 1024

chunk:
  split_headings: [h2, h3]
  target_tokens: [200, 800]
  max_tokens: 1000
  min_merge_tokens: 100
  overlap_tokens: 50

enrich:
  questions_per_ref: [3, 7]
  languages: [en, zh]
  llm: gpt-5.5

retrieval:
  index: both             # body | questions | both
  search: hybrid          # vector | hybrid
  top_k: 8
  rrf_k: 60
  rerank: true
  reranker: bge-reranker-v2-m3

generation:
  llm: gpt-5.5
  require_citations: true
  refuse_when_no_context: true

eval:
  golden_size: 50
  judge: gpt-5.5
  framework: ragas         # + promptfoo/deepeval for matrix sweep
```

---

## 13. Build order (suggested milestones)

1. **Ingestion + chunking** → produce `refs` rows (no embeddings yet); eyeball chunk quality on 5–10 pages.
2. **Enrichment** → questions, summaries, captions, `content_type`/`component`.
3. **DB load** → embed + populate `refs`/`descriptions`/`summaries` + tsvectors.
4. **Retrieval** → filter → hybrid (RRF) → rerank; expose `index`/`search`/`rerank` as config flags (enables the matrix).
5. **Answer** → gpt-5.5 with citations + refusal.
6. **Eval harness + golden set** → generate (decoupled), human spot-check, wire RAGAS + sweeper.
7. **Run the matrix** → produce the comparison report → pick the winner.

---

## 14. Open items / TBD

- **Embedding model** final pick — defaulted to a multilingual model; pluggable via config.
- **Query language** — confirmed: support multilingual (EN + ZH).
- **`component` vocabulary** — derive the real value set from a sample of the slice during §6.3.
- **Metadata-filter as a variant** — out of the core ladder; add only if free-text retrieval proves noisy across facets.
