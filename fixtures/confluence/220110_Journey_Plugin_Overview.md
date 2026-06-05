---
page_id: "220110"
title: "Journey Plugin Overview"
space: "DEPT"
source_url: "https://confluence.local/x/Journey-Plugin-Overview"
owner: "alice"
labels: ["plugin", "journey"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Plugins"]
update_at: "2026-05-15T11:00:00Z"
confluence_version: 4
---

## What is the Journey Plugin

The **Journey plugin** orchestrates user journeys: it decides which next step or message
a user should receive based on journey rules. It consumes messages produced upstream by
the DM plugin.

## Receiving from DM

The Journey plugin receives messages from the **DM plugin** via the **adaptor**. The
incoming payload includes `campaign_id` and `user_id`. If the adaptor is in async mode,
messages are buffered before the journey engine picks them up.

## Configuration

| Param                     | Default | Notes                          |
|---------------------------|---------|--------------------------------|
| `max_concurrent_journeys` | 50      | concurrent journeys per worker |
