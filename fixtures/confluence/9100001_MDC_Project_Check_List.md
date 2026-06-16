---
page_id: "9100001"
title: "MDC Project Check List"
space: "MDC"
source_url: "https://confluence.local/x/MDC-Project-Check-List"
owner: "mdc-team"
labels: ["mdc", "engagement", "onboarding"]
domains: ["Q2 - Engagement", "MDC Onboarding"]
tree_path: ["Q2 - Engagement", "MDC Onboarding", "MDC Project Check List"]
update_at: "2026-05-20T10:00:00Z"
confluence_version: 31
---

## MDC supported notification channels

MDC supports several messaging channels for delivery. Each channel has its own
delivery mode, content template, and bounce back handling.

| Channel | Delivery Mode | Template | Bounce Back |
|---|---|---|---|
| PN | real-time | PN content template | retry once |
| SMS | batched | SMS content template | resend after 5 min |
| Email | batched | Email content template | resend after 30 min |
| Letter | daily file | Letter content template | manual follow-up |
| Whatsapp | real-time | Whatsapp content template | retry once |

## MDC Management Portal

The MDC Management Portal (also called the MDC Messaging Platform) is where teams
manage channels and request access rights for each environment.

| Environment | Link | Notes |
|---|---|---|
| Portal link | https://mdc-portal.example.local | landing page |
| UAT Access right | https://mdc-portal-uat.example.local/access | request via portal |
| PROD Access right | https://mdc-portal-prod.example.local/access | needs line-manager approval |

## Notification Use Case Setup

A notification use case is created in the portal and mapped to a message path.

| Use Case ID | Name | SLO baseline |
|---|---|---|
| M488 | Payment OTP notification | 5 min |
| M489 | Statement ready notification | 30 min |

## MDC project engagement process

Engagement steps

1. Raise an onboarding enquiry via the engagement contact point.
2. Confirm requirements with the MDC governance Process owner.
3. Schedule the technical onboarding session and confirm channels.
