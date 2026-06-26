from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from backend.ports import PageRef, RawPage


class JsonConfluenceSource:
    """Read incoming pages from a directory of JSON files.

    This is the ingestion entry point for *new* content that does not (yet) live
    in Confluence: drop one JSON file per page (or a single file holding a JSON
    array of pages) into ``paths.incoming_dir`` and run ``pipeline ingest``.

    Each page is a ``RawPage``-shaped object. Only ``page_id``, ``title`` and
    ``body_md`` are strictly required; everything else is defaulted so a hand-
    written file stays small. ``confluence_version`` / ``update_at`` matter for
    conflict resolution (newer wins), so set them when a JSON page is meant to
    supersede an existing value.
    """

    def __init__(self, incoming_dir: Path):
        self.incoming_dir = Path(incoming_dir)
        self._pages: Dict[str, RawPage] = {}
        self._load()

    def _load(self) -> None:
        if not self.incoming_dir.exists():
            return
        for path in sorted(self.incoming_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload if isinstance(payload, list) else [payload]
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError(f"Incoming page file is not an object/array of objects: {path}")
                page = self._normalize(record, path)
                self._pages[page["page_id"]] = page

    def _normalize(self, record: Dict, path: Path) -> RawPage:
        for required in ("page_id", "title", "body_md"):
            if not str(record.get(required) or "").strip():
                raise ValueError(f"Incoming page {path.name} missing required field {required!r}")
        domains = list(record.get("domains") or record.get("module") or [])
        body = str(record["body_md"])
        return {
            "page_id": str(record["page_id"]),
            "title": str(record["title"]),
            "space": str(record.get("space", "")),
            "source_url": str(record.get("source_url", "")),
            "owner": str(record.get("owner", "")),
            "labels": list(record.get("labels", [])),
            "captured_at": str(record.get("captured_at", "2026-06-26T00:00:00Z")),
            "update_at": str(record.get("update_at", "")),
            "confluence_version": int(record.get("confluence_version", 0)),
            "tree_path": list(record.get("tree_path", [])),
            "domains": domains,
            "card_worthy": bool(record.get("card_worthy", bool(domains))),
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


class CompositeConfluenceSource:
    """Union several sources so *new* JSON pages ingest alongside existing content.

    Later sources win on a ``page_id`` collision (a JSON file can supersede an
    existing page), while new page_ids simply add to the corpus — which is what
    surfaces a conflict when the new page gives a different value for a field the
    existing pages already cover. Used by provider ``file+json``.
    """

    def __init__(self, sources: List["object"]):
        self.sources = list(sources)

    def _owner_map(self) -> Dict[str, object]:
        owner: Dict[str, object] = {}
        for source in self.sources:
            for ref in source.list_pages(""):
                owner[ref["page_id"]] = source
        return owner

    def list_pages(self, slice_root: str) -> List[PageRef]:
        owner = self._owner_map()
        refs: List[PageRef] = []
        seen = set()
        for page_id, source in owner.items():
            if page_id in seen:
                continue
            seen.add(page_id)
            for ref in source.list_pages(slice_root):
                if ref["page_id"] == page_id:
                    refs.append(ref)
                    break
        return sorted(refs, key=lambda item: item["page_id"])

    def get_page(self, page_id: str) -> RawPage:
        return self._owner_map()[page_id].get_page(page_id)
