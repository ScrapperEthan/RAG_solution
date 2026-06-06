---
page_id: "200066"
title: "DM Plugin Troubleshooting"
space: "DEPT"
source_url: "https://confluence.local/x/DM-Plugin-Troubleshooting"
owner: "bob"
labels: ["plugin", "troubleshoot", "faq"]
module: ["Integration & API standard", "Delivery & tracking standard", "Operations & release standard"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Plugins"]
update_at: "2026-05-19T16:00:00Z"
confluence_version: 4
---

## Common Errors

- **DM-429**: the DM plugin is rate limited by a downstream channel. Reduce `batch_size`
  or add backoff.
- **DM-503**: downstream channel unavailable; messages are requeued.

## Retry Behaviour

The DM plugin **supports retry configuration**; configure it according to your channel's
rate limits. (This page does not state the default number of retries — see the DM Plugin
Overview Configuration for the actual value.)

## FAQ

**Q: Does a DM-429 drop messages?** No — affected messages are retried subject to the
retry configuration.
