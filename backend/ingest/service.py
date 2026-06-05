from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from backend.ingest.chunk import chunk_page
from backend.ports import ConfluenceSource, RawPage
from backend.util import clean_dir, ensure_dir, write_json


class IngestionService:
    def __init__(self, source: ConfluenceSource, outputs_dir: Path, chunk_config: Optional[Dict] = None):
        self.source = source
        self.outputs_dir = outputs_dir
        self.chunk_config = chunk_config or {}

    def run(self, slice_root: str) -> Dict[str, int]:
        capture_dir = clean_dir(self.outputs_dir / "capture")
        refs_dir = clean_dir(self.outputs_dir / "refs")
        pages = self.source.list_pages(slice_root)
        all_refs: List[Dict] = []
        for page_ref in pages:
            page = self.source.get_page(page_ref["page_id"])
            self._write_capture(capture_dir, page)
            refs = chunk_page(page, self.chunk_config)
            all_refs.extend(refs)
            write_json(refs_dir / f"refs_{page['page_id']}.json", refs)
        write_json(self.outputs_dir / "refs.json", all_refs)
        return {"pages": len(pages), "refs": len(all_refs)}

    def _write_capture(self, capture_dir: Path, page: RawPage) -> None:
        ensure_dir(capture_dir)
        write_json(capture_dir / f"{page['page_id']}.json", page)
