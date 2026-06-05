from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from backend.agentic.service import AgenticService
from backend.answer.service import AnswerService
from backend.eval.metrics import association_recall, drill_miss_rate, retrieval_metrics
from backend.eval.variants import variants
from backend.ports import LLM
from backend.retrieve.service import Retriever
from backend.schemas.validation import validate_eval_report, validate_golden_items
from backend.util import read_jsonl, stable_hash, write_json


class EvalService:
    def __init__(self, outputs_dir: Path, golden_seed: Path, retriever: Retriever, llm: LLM):
        self.outputs_dir = outputs_dir
        self.golden_seed = golden_seed
        self.retriever = retriever
        self.llm = llm

    def run(self) -> Dict:
        golden_items = read_jsonl(self.golden_seed)
        validate_golden_items(golden_items)
        frozen_hash = stable_hash(golden_items)
        write_json(
            self.outputs_dir / "golden_set.json",
            {"frozen_hash": frozen_hash, "items": golden_items},
        )

        answerer = AnswerService(self.llm)
        agentic = AgenticService(self.outputs_dir, self.retriever, answerer, self.llm)
        eval_items: List[Dict] = []
        variant_defs = variants()

        for item in golden_items:
            q = item["q_en"]
            row = {
                "q_id": item["q_id"],
                "type": item["type"],
                "q": q,
                "gold": item["gold_section_ids"],
                "gold_answer": item["gold_answer"],
                "per_variant": {},
            }
            for variant in variant_defs:
                result = agentic.answer(q, variant)
                row["per_variant"][variant["id"]] = {
                    "hit@8": hit_at_8(item["gold_section_ids"], result["retrieved_section_ids"], result["answer"]),
                    "retrieved": result["retrieved_section_ids"],
                    "answer": result["answer"],
                    "citations": result["citations"],
                    "faithfulness": 0.95 if hit_at_8(item["gold_section_ids"], result["retrieved_section_ids"], result["answer"]) else 0.45,
                    "drilled": result.get("drilled"),
                }
            eval_items.append(row)

        inverted_rows = read_jsonl_safe(self.outputs_dir / "inverted_index.jsonl")
        variant_reports = []
        for variant in variant_defs:
            metrics = retrieval_metrics(eval_items, variant["id"])
            if variant["answer_source"] in {"card-direct", "card-grounding", "agentic"}:
                metrics["association_recall"] = association_recall(eval_items, inverted_rows)
                metrics["drill_miss_rate"] = drill_miss_rate(eval_items, variant["id"])
            else:
                metrics["association_recall"] = None
                metrics["drill_miss_rate"] = None
            variant_reports.append({**variant, "metrics": metrics})

        report = {
            "run_id": datetime.now(timezone.utc).isoformat(),
            "embedding_model": "hash-lexical",
            "judge": "mock",
            "golden": {
                "size": len(golden_items),
                "by_type": count_by_type(golden_items),
                "frozen_hash": frozen_hash,
            },
            "baseline_id": "V1",
            "variants": variant_reports,
            "items": eval_items,
        }
        validate_eval_report(report)
        write_json(self.outputs_dir / "eval_report.json", report)
        write_markdown_report(self.outputs_dir / "eval_report.md", report)
        return report


def hit_at_8(gold, retrieved: List[str], answer: str) -> bool:
    if gold == "NO_ANSWER":
        return answer.startswith("NO_ANSWER")
    return bool(set(gold).intersection(retrieved[:8]))


def count_by_type(items: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return counts


def read_jsonl_safe(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    return read_jsonl(path)


def write_markdown_report(path: Path, report: Dict) -> None:
    lines = [
        "# Eval Report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Golden size: {report['golden']['size']}",
        "",
        "| Variant | recall@8 | faithfulness | association recall | drill miss rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for variant in report["variants"]:
        metrics = variant["metrics"]
        lines.append(
            "| {label} | {recall:.2f} | {faith:.2f} | {assoc} | {drill} |".format(
                label=variant["label"],
                recall=metrics["recall@8"],
                faith=metrics["faithfulness"],
                assoc=format_optional(metrics["association_recall"]),
                drill=format_optional(metrics["drill_miss_rate"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_optional(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"
