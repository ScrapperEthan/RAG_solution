---
page_id: "160033"
title: "Message Inventory"
space: "DEPT"
source_url: "https://confluence.local/x/Message-Inventory"
owner: "dan"
labels: ["inventory", "messages"]
module: ["Template & content standard", "Delivery & tracking standard"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Message Inventory"]
update_at: "2026-05-10T10:00:00Z"
confluence_version: 3
---

## Overview

This page lists the message types in scope for the 2026 project and how each is produced
and consumed.

## Batch Processing Notes

Message batches are processed by the **DM plugin**; the number of messages per batch is
governed by the DM plugin configuration (`batch_size`). Teams sizing throughput should
refer to the DM plugin configuration rather than assuming a fixed number here.
