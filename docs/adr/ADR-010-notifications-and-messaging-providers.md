# ADR-010 — Notifications and messaging providers

- Status: Proposed — provider choices require human approval (paid external services, CLAUDE.md §5)
- Spec: §17 (channels, templates, consent, delivery tracking, 15-min fallback), §22.2, §22.3, §21.5

## Context
Application code raises a `notification_type`; the notification service chooses channel, template, language, variables;
no WhatsApp logic outside `notifications/` (§17.2). Email is always sent as record; WhatsApp is primary for suppliers;
every flow works with email + link alone (§4.10). Templates in English and Hindi.

## Options considered
| Concern | Options | Recommendation |
| --- | --- | --- |
| WhatsApp | Meta WhatsApp Cloud API direct; Indian BSP (e.g. Gupshup, Interakt, Kaleyra) | **Meta Cloud API direct** behind an adapter: no BSP markup, official webhooks; BSP adapter possible later if template approval/support needs a partner |
| Email | AWS SES (ap-south-1), SendGrid, Postmark | **AWS SES ap-south-1** (same cloud/region as ADR-017, DKIM/SPF, bounce via SNS → webhook) |
| SMS | MSG91, Gupshup, AWS SNS (DLT registration needed in India) | **not built in R1** (A-65); interface only |
| In-app | `messages` rows with `channel='in_app'` + polling endpoint | as stated |

## Decision
1. `notifications.service.notify(notification_type, object, recipients, variables)` writes one `messages` row per
   (recipient, channel) with status `queued` and a deterministic `idempotency_key`, then enqueues send jobs. Called only
   from outbox handlers / scheduled jobs (never inside the request transaction for external sends).
2. Channel selection per recipient (§17.1, §17.3): supplier contact → WhatsApp if `opted_in` and mobile present, **and**
   email always; internal user → in-app + email. Opt-out switches to email; never blocks.
3. Templates: `api/app/notifications/templates/{en,hi}/{NOTIFICATION_TYPE}.{whatsapp|email}.*`; WhatsApp templates map to
   pre-approved provider template names; free-form only inside the 24-h window (not used in R1).
   Language: English unless decided otherwise (A-12).
4. Delivery tracking: provider webhooks → `messages.status` forward-only, `provider_message_id`; click tracking via link
   redirect `/s/{token}` updates `clicked_at` of the message that carried it; transitions also logged to `activity_log`.
5. Fallback: `notifications.fallback_check` every minute: WhatsApp message `failed`, or `sent` but not `delivered`
   within 15 min → send email (if not already sent for that notification) (§17.4).
6. STOP/UNSUBSCRIBE inbound → `contact_consents` opted_out (A-67 scope) → switches channel.
7. Local/CI: fake WhatsApp adapter (records calls), Mailpit SMTP; staging: provider sandboxes.

## Consequences
- Requires: Meta Business verification, WhatsApp sender number, template approval (en + hi), SES domain verification
  and production access — lead time weeks; start in P05 planning.
- No provider SDK outside `notifications/channels/` (import-linter).

## Revisit when
- WhatsApp delivery failure rate > 5% weekly, or template approval latency blocks a release (→ consider BSP), or
- a customer requires SMS (→ resolve A-65 with DLT registration).
