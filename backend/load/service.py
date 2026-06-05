from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from backend.ports import Embedder, VectorStore
from backend.util import read_json, write_json


class LoadService:
    def __init__(self, outputs_dir: Path, embedder: Embedder, store: VectorStore):
        self.outputs_dir = outputs_dir
        self.embedder = embedder
        self.store = store

    def run(self) -> Dict[str, int]:
        refs = read_json(self.outputs_dir / "refs.json")
        refs = assign_ref_ids(refs)
        ref_by_section = {row["section_id"]: row for row in refs}
        ref_by_page = first_ref_by_page(refs)

        ref_texts = [row["title"] + "\n" + " > ".join(row["heading_path"]) + "\n" + row["body_md"] for row in refs]
        ref_embeddings = self.embedder.embed(ref_texts, kind="passage")
        for row, embedding in zip(refs, ref_embeddings):
            row["body_embedding"] = embedding

        descriptions = build_descriptions(self.outputs_dir, ref_by_section)
        desc_embeddings = self.embedder.embed([row["text"] for row in descriptions], kind="passage") if descriptions else []
        for row, embedding in zip(descriptions, desc_embeddings):
            row["embedding"] = embedding

        summaries = build_summaries(self.outputs_dir, ref_by_page)
        summary_embeddings = self.embedder.embed([row["text"] for row in summaries], kind="passage") if summaries else []
        for row, embedding in zip(summaries, summary_embeddings):
            row["embedding"] = embedding

        self.store.init_schema()
        self.store.upsert_refs(refs)
        self.store.upsert_descriptions(descriptions)
        self.store.upsert_summaries(summaries)
        write_json(self.outputs_dir / "loaded_refs.json", refs)
        write_json(self.outputs_dir / "loaded_descriptions.json", descriptions)
        write_json(self.outputs_dir / "loaded_summaries.json", summaries)
        return {"refs": len(refs), "descriptions": len(descriptions), "summaries": len(summaries)}


def assign_ref_ids(refs: List[Dict]) -> List[Dict]:
    rows = []
    for idx, ref in enumerate(refs, start=1):
        row = dict(ref)
        row["ref_id"] = idx
        rows.append(row)
    return rows


def first_ref_by_page(refs: List[Dict]) -> Dict[str, Dict]:
    result: Dict[str, Dict] = {}
    for ref in refs:
        result.setdefault(ref["page_id"], ref)
    return result


def build_descriptions(outputs_dir: Path, ref_by_section: Dict[str, Dict]) -> List[Dict]:
    descriptions: List[Dict] = []
    desc_id = 1
    for path in sorted((outputs_dir / "map").glob("map_*.json")):
        page = read_json(path)
        for section in page["sections"]:
            sid = f"{page['page_id']}#{section['heading_path'][-1]}"
            ref = ref_by_section.get(sid)
            if not ref:
                continue
            texts: List[Tuple[str, str]] = []
            texts.extend(("question", question) for question in section["questions_en"])
            texts.extend(("question", question) for question in section["questions_zh"])
            texts.append(("summary", section["summary_en"]))
            texts.append(("summary", section["summary_zh"]))
            for kind, text in texts:
                descriptions.append(
                    {
                        "desc_id": desc_id,
                        "ref_id": ref["ref_id"],
                        "kind": kind,
                        "lang": "zh" if contains_cjk(text) else "en",
                        "text": text,
                    }
                )
                desc_id += 1
    return descriptions


def build_summaries(outputs_dir: Path, ref_by_page: Dict[str, Dict]) -> List[Dict]:
    rows: List[Dict] = []
    sum_id = 1
    for path in sorted((outputs_dir / "map").glob("map_*.json")):
        page = read_json(path)
        first_ref = ref_by_page.get(page["page_id"])
        if not first_ref:
            continue
        for lang_key in ("summary_en", "summary_zh"):
            rows.append(
                {
                    "sum_id": sum_id,
                    "ref_id": first_ref["ref_id"],
                    "page_id": page["page_id"],
                    "tree_path": page["tree_path"],
                    "text": page["page_summary"][lang_key],
                }
            )
            sum_id += 1
    return rows


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)
