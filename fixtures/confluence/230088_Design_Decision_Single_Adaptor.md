---
page_id: "230088"
title: "Design Decision: Single Adaptor Layer"
space: "DEPT"
source_url: "https://confluence.local/x/ADR-Single-Adaptor"
owner: "carol"
labels: ["design", "decision", "adr"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Design"]
update_at: "2026-05-12T10:00:00Z"
confluence_version: 2
---

## Decision

We will use a **single adaptor** layer between the DM plugin and the Journey plugin,
rather than point-to-point integrations between every producer and consumer.

## Rationale

A single adaptor means format changes are handled in one place. Point-to-point would
require N×M mappings and make migrations (e.g., SFMC) far riskier. The adaptor also lets
DM and Journey deploy independently.

## Consequences

The adaptor becomes a critical path component and must be highly available. Its payload
mapping (see the Adaptor page) is the single source of truth for field translation.
