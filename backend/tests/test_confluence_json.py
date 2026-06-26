"""JSON ingestion source: new pages arriving as JSON files."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.adapters.confluence_json import CompositeConfluenceSource, JsonConfluenceSource


class JsonConfluenceSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, payload) -> None:
        (self.inbox / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_reads_single_object_and_defaults_optional_fields(self) -> None:
        self._write("p1.json", {"page_id": "557281", "title": "Leave policy", "body_md": "# Leave\n10 days"})
        source = JsonConfluenceSource(self.inbox)
        page = source.get_page("557281")
        self.assertEqual(page["title"], "Leave policy")
        self.assertTrue(page["body_md"].startswith("# Leave"))
        self.assertEqual(page["confluence_version"], 0)
        self.assertEqual(page["labels"], [])
        self.assertEqual(page["domains"], [])

    def test_reads_array_file_and_module_alias(self) -> None:
        self._write(
            "batch.json",
            [
                {"page_id": "1", "title": "A", "body_md": "a", "module": ["人事"]},
                {"page_id": "2", "title": "B", "body_md": "b", "domains": ["请假"], "confluence_version": 3},
            ],
        )
        source = JsonConfluenceSource(self.inbox)
        self.assertEqual({r["page_id"] for r in source.list_pages("")}, {"1", "2"})
        self.assertEqual(source.get_page("1")["domains"], ["人事"])  # module -> domains
        self.assertEqual(source.get_page("2")["confluence_version"], 3)

    def test_slice_root_filters_by_tree_path(self) -> None:
        self._write("p.json", {"page_id": "9", "title": "T", "body_md": "x", "tree_path": ["Space", "Sub"]})
        source = JsonConfluenceSource(self.inbox)
        self.assertEqual(len(source.list_pages("Space")), 1)
        self.assertEqual(len(source.list_pages("Other")), 0)

    def test_missing_required_field_raises(self) -> None:
        self._write("bad.json", {"page_id": "x", "title": "no body"})
        with self.assertRaises(ValueError):
            JsonConfluenceSource(self.inbox)

    def test_absent_directory_is_empty_not_error(self) -> None:
        source = JsonConfluenceSource(self.inbox / "does-not-exist")
        self.assertEqual(source.list_pages(""), [])


class _StubSource:
    def __init__(self, pages):
        self._pages = {p["page_id"]: p for p in pages}

    def list_pages(self, slice_root):
        return [{"page_id": p["page_id"], "title": p["title"], "tree_path": p.get("tree_path", []),
                 "update_at": p.get("update_at", ""), "confluence_version": p.get("confluence_version", 0)}
                for p in self._pages.values()]

    def get_page(self, page_id):
        return self._pages[page_id]


class CompositeConfluenceSourceTest(unittest.TestCase):
    def test_union_adds_new_pages_and_later_source_wins_on_collision(self) -> None:
        base = _StubSource([
            {"page_id": "1", "title": "Base one", "body_md": "old"},
            {"page_id": "2", "title": "Base two", "body_md": "x"},
        ])
        incoming = _StubSource([
            {"page_id": "2", "title": "Updated two", "body_md": "new"},  # supersedes
            {"page_id": "3", "title": "Brand new", "body_md": "n"},      # adds
        ])
        composite = CompositeConfluenceSource([base, incoming])
        self.assertEqual({r["page_id"] for r in composite.list_pages("")}, {"1", "2", "3"})
        self.assertEqual(composite.get_page("2")["title"], "Updated two")  # later source wins
        self.assertEqual(composite.get_page("1")["title"], "Base one")


if __name__ == "__main__":
    unittest.main()
