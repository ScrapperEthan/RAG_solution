# inbox/ — new pages arriving as JSON

Drop new/updated pages here as JSON to ingest content that is not (yet) in the
md fixtures. One `RawPage` object per file, or a JSON array of them. Only
`page_id`, `title`, `body_md` are required; everything else is defaulted (see
`backend/adapters/confluence_json.py`).

`confluence_version` / `update_at` drive conflict resolution — set them newer
than the page you are superseding so the new value becomes the temporary
(newest-wins) choice and the conflict surfaces for review.

## Ingest it

- `provider: json` → ingest **only** these JSON pages.
- `provider: file+json` → ingest the existing md fixtures **plus** these JSON
  pages, so a new page can conflict with existing content. This is what
  `config.incoming.yaml` uses:

```bash
python -m backend.pipeline demo --config config.incoming.yaml
```

The bundled `example_updated_portal_link.json` changes the MDC portal link, which
collides with `C-0002 / Portal link / Link` and shows up in
`outputs/conflicts.jsonl` and in the approve page's red conflict panel.

See `handoff/35` for the full conflict-review flow.
