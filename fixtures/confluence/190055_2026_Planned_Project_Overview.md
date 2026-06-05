---
page_id: "190055"
title: "2026 Planned Project Overview"
space: "DEPT"
source_url: "https://confluence.local/x/2026-Planned-Project"
owner: "alice"
labels: ["overview", "index"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project"]
update_at: "2026-05-25T10:00:00Z"
confluence_version: 8
---

## Introduction

The 2026 Planned Project delivers the new messaging stack. Its main components are the
DM plugin, the Journey plugin, the adaptor, and the MDC OTP Service.

## Architecture at a Glance

Messages flow end to end as: **DM plugin → adaptor → Journey plugin**. One-time passwords
are handled separately by the **MDC OTP Service**. The adaptor decouples DM from Journey so
either side can change format independently.

## Component Index

- DM Plugin Overview — the delivery core
- Journey Plugin Overview — journey orchestration
- Adaptor — DM↔Journey bridge
- MDC OTP Service — one-time passwords
