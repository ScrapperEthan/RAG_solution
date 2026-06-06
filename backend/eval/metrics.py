from __future__ import annotations

import math
from typing import Dict, List, Optional

from backend.reducer.canonicals import canonical_id_in_text


def retrieval_metrics(items: List[Dict], variant_id: str) -> Dict[str, float]:
    hit5_scores = []
    hit8_scores = []
    recall5 = []
    recall8 = []
    mrr = []
    ndcg8 = []
    context_precision = []
    context_recall = []
    faithfulness = []
    answer_relevancy = []
    for item in items:
        gold = item["gold"]
        result = item["per_variant"][variant_id]
        retrieved = result["retrieved"]
        answer = result["answer"]
        if gold == "NO_ANSWER":
            correct_no_answer = answer.startswith("NO_ANSWER")
            hit5_scores.append(1.0 if correct_no_answer else 0.0)
            hit8_scores.append(1.0 if correct_no_answer else 0.0)
            recall5.append(1.0 if correct_no_answer else 0.0)
            recall8.append(1.0 if correct_no_answer else 0.0)
            mrr.append(1.0 if correct_no_answer else 0.0)
            ndcg8.append(1.0 if correct_no_answer else 0.0)
            context_precision.append(metric_value(result, "context_precision", 1.0 if correct_no_answer else 0.0))
            context_recall.append(metric_value(result, "context_recall", 1.0 if correct_no_answer else 0.0))
            faithfulness.append(metric_value(result, "faithfulness", 1.0 if correct_no_answer else 0.2))
            answer_relevancy.append(metric_value(result, "answer_relevancy", 1.0 if correct_no_answer else 0.2))
            continue

        gold_set = set(gold)
        retrieved5 = retrieved[:5]
        retrieved8 = retrieved[:8]
        hit5 = bool(gold_set.intersection(retrieved5))
        hit8 = bool(gold_set.intersection(retrieved8))
        hit5_scores.append(1.0 if hit5 else 0.0)
        hit8_scores.append(1.0 if hit8 else 0.0)
        recall5.append(len(gold_set.intersection(retrieved5)) / max(1, len(gold_set)))
        recall8.append(len(gold_set.intersection(retrieved8)) / max(1, len(gold_set)))
        mrr.append(first_relevant_rank_score(retrieved8, gold_set))
        ndcg8.append(ndcg(retrieved8, gold_set))
        relevant_count = len([sid for sid in retrieved8 if sid in gold_set])
        context_precision.append(metric_value(result, "context_precision", relevant_count / max(1, len(retrieved8))))
        context_recall.append(metric_value(result, "context_recall", relevant_count / max(1, len(gold_set))))
        faithfulness.append(metric_value(result, "faithfulness", 0.95 if hit8 else 0.45))
        answer_relevancy.append(metric_value(result, "answer_relevancy", 0.9 if answer and not answer.startswith("NO_ANSWER") else 0.35))

    return {
        "hit@5": avg(hit5_scores),
        "hit@8": avg(hit8_scores),
        "recall@5": avg(recall5),
        "recall@8": avg(recall8),
        "mrr": avg(mrr),
        "ndcg@8": avg(ndcg8),
        "faithfulness": avg(faithfulness),
        "answer_relevancy": avg(answer_relevancy),
        "context_precision": avg(context_precision),
        "context_recall": avg(context_recall),
    }


def association_recall(inverted_rows: List[Dict], canonicals: Dict[str, Dict]) -> Optional[float]:
    scores = []
    rows_by_cid: Dict[str, set] = {}
    for row in inverted_rows:
        rows_by_cid.setdefault(row["canonical_id"], set()).add(str(row["page_id"]))
    for cid, canonical in canonicals.items():
        gold_pages = set(canonical.get("related_pages", []))
        if not gold_pages:
            continue
        associated = rows_by_cid.get(cid, set())
        scores.append(len(gold_pages.intersection(associated)) / max(1, len(gold_pages)))
    return avg(scores) if scores else None


def drill_miss_rate(items: List[Dict], variant_id: str) -> Optional[float]:
    required = [item for item in items if item["type"] in {"identifier-lookup", "pointer-drill"}]
    misses = 0
    total = 0
    for item in required:
        drilled = item["per_variant"][variant_id].get("drilled")
        if drilled is None:
            continue
        total += 1
        if drilled is False:
            misses += 1
    if total == 0:
        return None
    return misses / total


def canonical_for_question(question: str, canonicals: Dict[str, Dict]) -> Optional[str]:
    return canonical_id_in_text(question, canonicals)


def first_relevant_rank_score(retrieved: List[str], gold_set: set) -> float:
    for idx, sid in enumerate(retrieved, start=1):
        if sid in gold_set:
            return 1.0 / idx
    return 0.0


def ndcg(retrieved: List[str], gold_set: set) -> float:
    dcg = 0.0
    for idx, sid in enumerate(retrieved, start=1):
        if sid in gold_set:
            dcg += 1.0 / math.log2(idx + 1)
    ideal = sum(1.0 / math.log2(idx + 1) for idx in range(1, min(len(gold_set), len(retrieved)) + 1))
    return dcg / ideal if ideal else 0.0


def avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def metric_value(result: Dict, key: str, fallback: float) -> float:
    value = result.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return fallback
