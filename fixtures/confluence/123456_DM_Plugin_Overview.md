---
page_id: "123456"
title: "DM Plugin Overview"
space: "DEPT"
source_url: "https://confluence.local/x/DM-Plugin-Overview"
owner: "alice"
labels: ["plugin", "delivery"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Plugins"]
update_at: "2026-05-20T10:00:00Z"
confluence_version: 7
---

## What is the DM Plugin

The Data Management plugin (**DM plugin**, sometimes abbreviated **DMP**) delivers
messages to downstream channels. It is the core component of the delivery pipeline and
is responsible for batching, retrying, and handing messages off to the Journey plugin.

## Configuration

| Param        | Default | Notes                         |
|--------------|---------|-------------------------------|
| `batch_size` | 500     | maximum allowed value is 1000 |
| `max_retry`  | 3       | per-message retry attempts    |

## How it connects to the Journey Plugin

After processing, the DM plugin hands messages to the **Journey plugin** through the
**adaptor**. The handshake payload includes `campaign_id` and `user_id`. See the
Journey Plugin page for the full handshake details.
