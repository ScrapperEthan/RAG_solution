---
page_id: "140020"
title: "Adaptor"
space: "DEPT"
source_url: "https://confluence.local/x/Adaptor"
owner: "bob"
labels: ["plugin", "integration"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Plugins"]
update_at: "2026-05-18T14:00:00Z"
confluence_version: 5
---

## What is the Adaptor

The **adaptor** (also spelled **adapter** in older documents) is the bridge between the
DM plugin and the Journey plugin. It translates the DM plugin's output into the format the
Journey plugin expects.

## Configuration

| Param          | Default | Notes                              |
|----------------|---------|------------------------------------|
| `adaptor_mode` | sync    | `sync` or `async`                  |

## Payload Mapping

The adaptor maps DM output fields to Journey input fields: `msg_id` → `message_id`,
`uid` → `user_id`. Unmapped fields are dropped.
