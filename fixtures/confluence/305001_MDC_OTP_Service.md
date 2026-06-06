---
page_id: "305001"
title: "MDC OTP Service"
space: "DEPT"
source_url: "https://confluence.local/x/MDC-OTP-Service"
owner: "carol"
labels: ["service", "otp", "mdc"]
module: ["MDC development guideline", "Integration & API standard"]
tree_path: ["06-Delivery", "10. Planned Project", "2026 Planned Project", "Services"]
update_at: "2026-04-30T08:00:00Z"
confluence_version: 2
---

## What is the MDC OTP Service

The **MDC OTP Service** generates and validates one-time passwords (**OTP**) for the MDC
flow. Note that "OTP" in this department most often refers specifically to this service,
not to OTP in general.

## OTP Generation Config

| Param        | Default | Notes                      |
|--------------|---------|----------------------------|
| `otp_length` | 6       | number of digits           |
| `otp_ttl`    | 300     | time-to-live in seconds    |

## Troubleshooting

If users report "OTP expired" errors, check clock skew between the issuing and validating
nodes; an OTP is only valid within `otp_ttl` seconds of issuance.
