from __future__ import annotations

import json
import re
from typing import Dict, List

from backend.ports import LLM


ANSWER_SYSTEM = """task: answer_from_context
Answer the user question using only the supplied Confluence references.

Return STRICT JSON: {"answer": string}.

Rules:
- Use only facts directly supported by supplied refs. Do not use outside
  knowledge and do not fabricate missing values.
- Every factual claim must be grounded in the refs. Prefer exact wording for
  config values, error codes, parameter names, API names, versions, and limits.
- Answer ONLY the specific question asked. Do not summarise the refs, add
  background, or pull in adjacent topics that appear in the supplied context but
  were not asked about: extra sections are evidence to search, not material to
  recite. A card drilldown may supply the card's whole section set — treat the
  unrelated ones as background, not as things to report.
- Give the shortest answer that fully resolves the question. When one value is
  asked, return that value; when the question asks to enumerate ("which/all/
  list/有哪些"), return the COMPLETE list and nothing beyond it.
- If the refs do not contain supporting context, the answer must start with
  "NO_ANSWER" and briefly say no answer was found in the supplied Confluence
  context.
- If refs disagree, state the conflict and prefer the newest source only when
  update/version evidence is present.
- Keep citations possible by making the answer traceable to the supplied
  section_ids/source URLs; do not cite sources not provided."""

ANSWER_SCHEMA = {"type": "object", "required": ["answer"]}


class AnswerService:
    def __init__(self, llm: LLM):
        self.llm = llm

    def answer_from_refs(self, query: str, refs: List[Dict]) -> Dict:
        section_ids = [ref["section_id"] for ref in refs]
        if should_refuse(query, refs):
            return {
                "answer": "NO_ANSWER — no answer found in the supplied Confluence context.",
                "citations": [],
                "retrieved_section_ids": section_ids,
                "contexts": [],
                "drilled": None,
            }
        response = self.llm.complete_json(
            ANSWER_SYSTEM,
            json.dumps(
                {
                    "query": query,
                    "refs": [
                        {
                            "section_id": ref["section_id"],
                            "title": ref.get("title", ""),
                            "heading_path": ref.get("heading_path", []),
                            "body_md": ref.get("body_md", ""),
                        }
                        for ref in refs
                    ],
                },
                ensure_ascii=False,
            ),
            schema=ANSWER_SCHEMA,
        )
        answer = response.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("answer_from_context must return a non-empty answer")
        citations = dedupe([ref["source_url"] for ref in refs[:3] if ref.get("source_url")])
        return {
            "answer": answer,
            "citations": citations,
            "retrieved_section_ids": section_ids,
            "contexts": [ref.get("body_md", "") for ref in refs],
            "drilled": None,
        }


def should_refuse(query: str, refs: List[Dict]) -> bool:
    """Refuse only when there is no evidence to ground an answer.

    Refusal is driven by evidence, not by hard-coded topics: if the caller
    supplied no usable refs there is nothing to ground an answer in, so we
    must refuse. Otherwise the grounded answerer (ANSWER_SYSTEM) decides — it
    returns NO_ANSWER itself when the supplied refs do not support the question.
    Do not special-case topics here (e.g. "sms"/"pricing"): those are real,
    answerable subjects in some corpora and topic keywords cannot tell whether
    the supplied refs actually cover them.
    """
    return not refs


# A query is treated as grounded only when a strict majority of its salient
# terms actually appear in the supplied refs. 0.6 keeps questions whose terms
# are mostly covered (>= 2/3) while refusing ones where only half (or fewer)
# of the salient terms are present — e.g. an out-of-scope question that merely
# shares the subject nouns with the refs ("sms", "mdc" both real corpus terms)
# but whose real focus ("price") is absent.
GROUNDING_THRESHOLD = 0.6

# Generic English function words. This is deliberately topic-agnostic: it must
# not encode anything about the corpus (no "sms"/"pricing"/"dm"), so the same
# gate works for the MDC knowledge base or any other corpus.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "do", "does", "did", "of", "for", "to", "in", "on", "at", "by", "and",
        "or", "as", "with", "that", "this", "these", "those", "it", "its",
        "we", "you", "they", "he", "she", "how", "what", "which", "who",
        "whom", "when", "where", "why", "can", "could", "would", "should",
        "will", "shall", "may", "might", "has", "have", "had", "not", "no",
        "but", "if", "then", "than", "so", "such", "into", "from", "about",
        "your", "our", "their", "there", "here", "out", "up", "off",
    }
)

_WORD = re.compile(r"[a-z0-9_]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。!?])\s+|\n+")


def synthesize_answer(query: str, refs: List[Dict]) -> str:
    """Generic, grounding-aware offline summary for the mock LLM.

    Builds a short answer ONLY from the supplied refs' title/body_md — it never
    keys off hard-coded topic strings, so it works for any corpus (including the
    real MDC content). When the query's salient terms are not actually present
    in the refs it returns a string starting with "NO_ANSWER", so out-of-scope
    questions refuse via evidence rather than via a topic keyword list. The real
    in-network LLM (ANSWER_SYSTEM) does the same grounding check with semantics;
    this is its deterministic offline stand-in.
    """
    if not refs:
        return "NO_ANSWER — no supplied Confluence context to ground an answer."

    ref_tokens = _ref_tokens(refs)
    salient = _salient_terms(query)
    if salient:
        missing = [term for term in salient if not _is_grounded(term, ref_tokens)]
        if (len(salient) - len(missing)) / len(salient) < GROUNDING_THRESHOLD:
            return (
                "NO_ANSWER — the supplied Confluence sections do not mention "
                + ", ".join(missing[:4])
                + "."
            )
    return _summarize_refs(refs, salient)


def _salient_terms(query: str) -> List[str]:
    """Content terms a grounded answer must be able to point at.

    Latin tokens of length >= 3 that are not generic function words. Short
    tokens and stopwords are dropped because they carry no grounding signal.
    Deduplicated, order-preserving. (Non-latin scripts yield no salient terms,
    so the gate is skipped for them and the answer falls back to a ref summary.)
    """
    seen: set[str] = set()
    terms: List[str] = []
    for token in _WORD.findall(query.lower()):
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _ref_tokens(refs: List[Dict]) -> frozenset:
    text = "\n".join(f"{ref.get('title', '')} {ref.get('body_md', '')}" for ref in refs).lower()
    return frozenset(_WORD.findall(text))


def _is_grounded(term: str, ref_tokens: frozenset) -> bool:
    """A term is present in the refs when a ref token matches it.

    Short tokens (<= 3 chars: "sms", "mdc", "per") must match a whole word so
    they do not spuriously hit inside longer words ("per" in "performance").
    Longer terms match as a prefix so morphological variants still ground the
    answer ("support" -> "supported", "channel" -> "channels"). This is a
    deterministic stand-in for the in-network LLM's semantic grounding.
    """
    if len(term) <= 3:
        return term in ref_tokens
    return any(token.startswith(term) for token in ref_tokens)


def _is_grounded_in(salient: List[str], sentence: str) -> bool:
    tokens = frozenset(_WORD.findall(sentence.lower()))
    return any(_is_grounded(term, tokens) for term in salient)


def _summarize_refs(refs: List[Dict], salient: List[str]) -> str:
    """Two-sentence summary stitched from the refs, preferring sentences that
    actually contain the query's salient terms so the answer stays on topic."""
    picked: List[str] = []
    for ref in refs:
        for sentence in _sentences(ref.get("body_md", "")):
            if not salient or _is_grounded_in(salient, sentence):
                picked.append(sentence)
                if len(picked) >= 2:
                    return " ".join(picked)
    if picked:
        return " ".join(picked)
    # No body sentence matched: fall back to the leading section's title/body so
    # answer_from_refs always receives a non-empty, ref-derived string.
    lead = refs[0]
    fallback = _sentences(lead.get("body_md", ""))
    if fallback:
        return fallback[0]
    return lead.get("title", "") or "See the cited Confluence sections."


def _sentences(body_md: str) -> List[str]:
    sentences = []
    for chunk in _SENTENCE_SPLIT.split(body_md or ""):
        cleaned = chunk.strip().lstrip("#-*> ").strip()
        if cleaned:
            sentences.append(cleaned)
    return sentences


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
