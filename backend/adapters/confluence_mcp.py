from __future__ import annotations

from typing import Any, Dict, List

from backend.ports import PageRef, RawPage


class McpConfluenceSource:
    """Intranet stub.

    opencode should implement this with the real Confluence MCP:
    - list the subtree under config["slice"]["root"]
    - fetch page metadata + Markdown body
    - parse tree_path into RawPage.tree_path
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def list_pages(self, slice_root: str) -> List[PageRef]:
        raise NotImplementedError("Intranet TODO: implement Confluence MCP subtree listing")

    def get_page(self, page_id: str) -> RawPage:
        raise NotImplementedError("Intranet TODO: implement Confluence MCP page fetch")

