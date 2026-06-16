from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from backend.ports import PageRef, RawPage


class FileConfluenceSource:
    """Read fixture pages whose Markdown files use YAML front matter."""

    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = fixtures_dir
        self._pages: Dict[str, RawPage] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted(self.fixtures_dir.glob("*.md")):
            page = self._read_page(path)
            self._pages[page["page_id"]] = page

    def _read_page(self, path: Path) -> RawPage:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise ValueError(f"Fixture page missing front matter: {path}")
        _, fm, body = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
        return {
            "page_id": str(meta["page_id"]),
            "title": str(meta["title"]),
            "space": str(meta.get("space", "")),
            "source_url": str(meta.get("source_url", "")),
            "owner": str(meta.get("owner", "")),
            "labels": list(meta.get("labels", [])),
            "captured_at": str(meta.get("captured_at", "2026-06-04T00:00:00Z")),
            "update_at": str(meta.get("update_at", "")),
            "confluence_version": int(meta.get("confluence_version", 0)),
            "tree_path": list(meta.get("tree_path", [])),
            "domains": list(meta.get("domains") or meta.get("module") or []),
            "card_worthy": bool(meta.get("card_worthy", bool(meta.get("domains") or meta.get("module")))),
            "body_md": body.strip() + "\n",
        }

    def list_pages(self, slice_root: str) -> List[PageRef]:
        refs: List[PageRef] = []
        for page in self._pages.values():
            tree = "/".join(page["tree_path"])
            if not slice_root or tree.startswith(slice_root):
                refs.append(
                    {
                        "page_id": page["page_id"],
                        "title": page["title"],
                        "tree_path": page["tree_path"],
                        "update_at": page["update_at"],
                        "confluence_version": page["confluence_version"],
                    }
                )
        return sorted(refs, key=lambda item: item["page_id"])

    def get_page(self, page_id: str) -> RawPage:
        return self._pages[page_id]
