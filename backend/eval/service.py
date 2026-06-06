from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from backend.agentic.service import AgenticService
from backend.answer.service import AnswerService
from backend.config import resolve_path
from backend.eval.metrics import association_recall, drill_miss_rate, retrieval_metrics
from backend.eval.ragas_judge import score_variant_with_ragas
from backend.eval.variants import variants
from backend.factory import build_embedder
from backend.ports import LLM
from backend.reducer.canonicals import load_vocabulary
from backend.retrieve.service import Retriever
from backend.schemas.validation import validate_eval_report, validate_golden_items
from backend.util import read_jsonl, stable_hash, write_json


class EvalService:
    def __init__(self, outputs_dir: Path, golden_seed: Path, retriever: Retriever, llm: LLM, config: Dict):
        self.outputs_dir = outputs_dir
        self.golden_seed = golden_seed
        self.retriever = retriever
        self.llm = llm
        self.config = config

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
        rerank_status_by_variant: Dict[str, str] = {}

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
                if variant.get("rerank"):
                    rerank_status_by_variant[variant["id"]] = self.retriever.last_rerank_status
                row["per_variant"][variant["id"]] = {
                    "hit@8": hit_at_8(item["gold_section_ids"], result["retrieved_section_ids"], result["answer"]),
                    "retrieved": result["retrieved_section_ids"],
                    "answer": result["answer"],
                    "citations": result["citations"],
                    "contexts": result.get("contexts", []),
                    "faithfulness": 0.95 if hit_at_8(item["gold_section_ids"], result["retrieved_section_ids"], result["answer"]) else 0.45,
                    "drilled": result.get("drilled"),
                }
            eval_items.append(row)

        metric_source = "mock-deterministic"
        if self.config.get("eval", {}).get("judge") != "mock":
            metric_source = self._apply_ragas_scores(eval_items, variant_defs)

        inverted_rows = read_jsonl_safe(self.outputs_dir / "inverted_index.jsonl")
        canonicals = load_vocabulary(resolve_path(self.config["paths"]["keyword_table"]))
        variant_reports = []
        for variant in variant_defs:
            metrics = retrieval_metrics(eval_items, variant["id"])
            if variant["answer_source"] in {"card-direct", "card-grounding", "agentic"}:
                metrics["association_recall"] = association_recall(inverted_rows, canonicals)
                metrics["drill_miss_rate"] = drill_miss_rate(eval_items, variant["id"])
            else:
                metrics["association_recall"] = None
                metrics["drill_miss_rate"] = None
            report_variant = {**variant, "metrics": metrics}
            if variant.get("rerank"):
                report_variant["rerank_status"] = rerank_status_by_variant.get(variant["id"], "unknown")
            variant_reports.append(report_variant)

        report = {
            "run_id": datetime.now(timezone.utc).isoformat(),
            "embedding_model": self.config.get("embedder", {}).get("model", self.config.get("providers", {}).get("embedder", "")),
            "judge": self.config.get("eval", {}).get("judge", self.config.get("providers", {}).get("llm", "")),
            "metric_source": metric_source,
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

    def _apply_ragas_scores(self, eval_items: List[Dict], variant_defs: List[Dict]) -> str:
        embedder = build_embedder(self.config)
        statuses = []
        for variant in variant_defs:
            scores, status = score_variant_with_ragas(eval_items, variant["id"], self.llm, embedder)
            statuses.append(status)
            if not scores:
                continue
            for row, score in zip(eval_items, scores):
                row["per_variant"][variant["id"]].update(score)
        if statuses and all(status == "ragas" for status in statuses):
            return "ragas"
        return "; ".join(sorted(set(statuses))) if statuses else "ragas-unavailable"


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
        f"- Metric source: `{report.get('metric_source', 'unknown')}`",
        f"- Golden size: {report['golden']['size']}",
        "",
        "| Variant | hit@8 | recall@8 | faithfulness | association recall | drill miss rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant in report["variants"]:
        metrics = variant["metrics"]
        lines.append(
            "| {label} | {hit:.2f} | {recall:.2f} | {faith:.2f} | {assoc} | {drill} |".format(
                label=variant["label"],
                hit=metrics["hit@8"],
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
