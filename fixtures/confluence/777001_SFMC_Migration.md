---
page_id: "777001"
title: "SFMC Migration"
space: "DEPT"
source_url: "https://confluence.local/x/SFMC-Migration"
owner: "bob"
labels: ["migration", "sfmc"]
module: ["Channel standard", "Delivery & tracking standard", "Operations & release standard"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Migration"]
update_at: "2026-05-28T09:00:00Z"
confluence_version: 3
---

## Overview

This page tracks the migration from the legacy delivery stack to SFMC. It covers
configuration changes to existing components, including the DM plugin.

## DM Plugin Config (post-migration)

After migration, the **DM plugin** `batch_size` is increased to **1000** to handle the
higher post-migration volume. This supersedes the previous default. `max_retry` is
unchanged.

## Known Issues

During cutover, duplicate sends were observed when `batch_size` was changed without
draining the queue first. Drain before changing batch configuration.
