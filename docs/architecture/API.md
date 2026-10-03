# QualLoop — API Contract (Phase 0)

Source: blueprint §7 (commands only), §9 C7 (supplier exposure), §16, §21, §22.2, §24.2. Decisions: ADR-003, ADR-008, ADR-009.
All paths below are relative to the base path **`/api/v1`** (e.g. `POST /ncrs` is served at `POST /api/v1/ncrs`).
Health endpoints are unversioned: `GET /healthz`, `GET /readyz`.

---

## 1. Conventions

### 1.1 Command vs query

| Kind | Method | Shape | Effects |
| --- | --- | --- | --- |
| Command | `POST` only | `/resource` (create) or `/resource/{id}/<verb>` | one transaction: authorise → validate → mutate → `activity_log` → `outbox_events` (ADR-003). Returns the updated resource read-model |
| Query | `GET` only | `/resource`, `/resource/{id}`, `/metrics/...` | no writes, except export/download which writes `activity_log` (§16 C14) |

There is no `PUT`/`PATCH`/`DELETE` on any domain resource (§7 "No generic update status endpoint", §7.5 no hard deletes).
Non-status master-data edits are commands too (`POST /suppliers/{id}/update`).

### 1.2 Authentication

| Principal | Credential | Where | Tenant resolution |
| --- | --- | --- | --- |
| Internal user | Cookie `ql_session` (opaque 32-byte random, HttpOnly, Secure, SameSite=Lax, path `/`); server-side session in Redis keyed by SHA-256 of the token | All non-supplier routes | session → `tenant_id` |
| Supplier contact | Cookie `ql_sup` (HMAC-signed `(tenant_id, supplier_session_id)`, HttpOnly, Secure, SameSite=Lax, path `/api/v1/supplier`) | `/supplier/*` routes only | signed value; then `supplier_sessions` row under RLS |
| Magic-link holder (pre-OTP) | Token only once, in the body of the server-to-server `POST /supplier-access/exchange` from the Next.js `/s/{token}` route handler; afterwards HttpOnly cookie `ql_pre` (signed `(tenant_id, magic_link_id)`, 15 min, `Path=/`) | `/supplier-access/*` only | exchange: `app_resolve_magic_link(sha256(token))`; then cookie (D-4, ADR-009) |
| Provider webhooks | Provider signature header (HMAC / Meta `X-Hub-Signature-256`) | `/webhooks/*` | `app_resolve_provider_message` / `app_resolve_contacts_by_mobile` |

CSRF: state-changing requests with cookie auth must send header `X-CSRF-Token` equal to the `ql_csrf` cookie (double-submit) and pass an `Origin` check.
Supplier cookie is not accepted on internal routes and vice versa.

### 1.3 Roles and permissions (§2.2; ADR-008)

| Code | Meaning |
| --- | --- |
| `A` | role `admin` |
| `Q` | role `quality` (Admin also holds every `Q` permission — SPEC-GAP A-70) |
| `V` | role `viewer` — queries only; never commands; no Excel export, no original-file download (A-70) |
| `+CA` | additionally requires `users.can_approve = true` |
| `A∨CA` | Admin **or** `can_approve` |
| `S` | supplier session scoped to the object (no internal user may call `/supplier/*`) |
| `SYS` | system/worker actor only — not exposed over HTTP |

Plant scope (A-04): for `Q`/`V`, plant-scoped objects (receipts, NCRs, SCARs, defect events, effectiveness, plant metrics)
are visible and actionable only when `plant_id ∈ users.plant_ids`; Admin sees all plants. Out-of-scope → `404`.
Supplier-level objects (suppliers, contacts, documents, debit notes) are tenant-wide.

### 1.4 Error format (RFC 9457 `application/problem+json`)

```json
{
  "type": "https://qualloop.in/problems/invalid-transition",
  "title": "This SCAR cannot be accepted in its current state",
  "status": 409,
  "code": "invalid_transition",
  "detail": "SCAR-2611-014 is SENT_BACK. Accept is allowed from RESPONSE_SUBMITTED or UNDER_REVIEW.",
  "instance": "/api/v1/scars/0192…/accept",
  "request_id": "01J…",
  "errors": [{"field": "reason", "code": "required", "message": "Give a reason for this change."}]
}
```

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `bad_request` | malformed JSON, bad cursor |
| 401 | `unauthenticated` | no/expired session |
| 403 | `forbidden` | authenticated but role / `can_approve` missing (same-tenant object only) |
| 404 | `not_found` | absent, other tenant, outside plant scope, or outside supplier-session scope (never reveals existence) |
| 409 | `invalid_transition` | state machine guard failed |
| 409 | `conflict` | concurrent modification / idempotency key in flight |
| 410 | `link_invalid` | supplier link expired, revoked, used up, or contact disabled — one generic message (no reason disclosed) |
| 413 | `payload_too_large` | upload > 20 MB (§20.2) |
| 415 | `unsupported_media_type` | upload not PDF/JPG/PNG by magic bytes |
| 422 | `validation_error` | field errors in `errors[]` |
| 422 | `invariant_violation` | money/quantity invariant (e.g. `allocation_exceeds_outstanding`); DB trigger errors are mapped to this |
| 422 | `idempotency_mismatch` | same Idempotency-Key, different body |
| 429 | `rate_limited` | login, OTP, upload, export limits; `Retry-After` header |
| 500 | `internal_error` | never includes stack traces; `request_id` for support |

Messages follow DESIGN_SPEC copy rules: what happened · what we did · what you can do.

### 1.5 Pagination (keyset)

- Request: `?limit=50&cursor=<opaque>`; `limit` 1–200, default 50.
- Response: `{"items": [...], "next_cursor": "<opaque>|null"}`. No total counts on large lists; count tiles come from dedicated query endpoints.
- Cursor = base64url(JSON `{"k": [last sort values..., last id], "s": "<sort name>"}`) + HMAC (tamper-evident). Sort is one of the endpoint's named sorts; ties broken by `id` (UUIDv7).
- Every list sort is backed by an index beginning with `tenant_id` (DATA_MODEL.md).

### 1.6 Idempotency

| Rule | Value |
| --- | --- |
| Header | `Idempotency-Key: <client UUID>` |
| Required on | `POST /ncrs`, `POST /debit-notes`, `POST /debit-notes/{id}/record-recovery`, `POST /write-offs`, `POST /imports/{batch}/confirm`, `POST /receipts`, `POST /defect-events`, every `/supplier/*` submit/upload command |
| Optional on | all other commands |
| Scope | `(tenant_id, actor_id, key)` |
| Retention | 24 h (`idempotency_keys.expires_at`, A-73) |
| Same key + same body hash | replay stored status + body; header `Idempotency-Replayed: true` |
| Same key + different body | `422 idempotency_mismatch` |
| Same key while first request in flight | `409 conflict` |
| Storage | written in the command's transaction (exactly-once with the business change) |

### 1.7 Versioning

- URL major version `/api/v1`. Additive changes (new fields, endpoints, enum values announced in advance) stay in v1.
- Breaking change → `/api/v2` served alongside v1 for ≥ 1 release; web client generated from OpenAPI and type-checked in CI.
- OpenAPI 3.1 generated by FastAPI at `/api/v1/openapi.json` (disabled in prod for anonymous users).

### 1.8 Common command body fields

| Field | Type | Rule |
| --- | --- | --- |
| `reason` | string 1–2000 | required where the table says "reason" |
| ids | UUID strings | |
| money | integer `*_paise` | > 0; never floats (ADR-005) |
| dates | `YYYY-MM-DD` | plant-local business date |
| instants | RFC 3339 with offset | stored UTC |

---

## 2. §24.2 command endpoints — all 24, verbatim

| # | Endpoint (verbatim §24.2) | Module | Transition / effect | Perm | Reason | Idem. | Events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `POST /ncrs` | ncr | create NCR (OPEN) + one attributed defect event per defect; `is_repeat`; capture timestamps | Q | — | required | `NCR_CREATED` |
| 2 | `POST /ncrs/{id}/contain` | ncr | OPEN → CONTAINED; containment rows | Q | if zero actions (A-14) | opt | `NCR_CONTAINED` |
| 3 | `POST /ncrs/{id}/decide-scar` | scar (decision gate, §22.1) | CONTAINED → AWAITING_SCAR / MONITOR / LOCAL_CLOSE; or "add to existing SCAR" → LINKED_TO_SCAR (A-16); major waiver needs `+CA` + reason (A-23) | Q (+CA for waiver) | yes | opt | `NCR_SCAR_DECIDED` (derived) |
| 4 | `POST /ncrs/{id}/dispose` | ncr | set/change disposition; `use_as_is` requires `+CA` | Q (+CA for use_as_is) | on change; always for use_as_is | opt | `NCR_DISPOSED` (derived) |
| 5 | `POST /ncrs/{id}/cancel` | ncr | any open → CANCELLED | A∨CA | yes | opt | `NCR_CANCELLED` (derived) |
| 6 | `POST /ncrs/{id}/reopen` | ncr | CLOSED → CONTAINED (A-05) | Q+CA | yes | opt | `NCR_REOPENED` (derived) |
| 7 | `POST /defect-events/{id}/attribute` | receipts | one of four decisions (§11.3); writes `defect_event_attributions` | Q | for qty_corrected / internal | opt | `DEFECT_EVENT_ATTRIBUTED` |
| 8 | `POST /suppliers/{id}/request-documents` | documents | bulk request all `not_requested` (and selected) requirements → REQUESTED, `due_at`; one `document_upload` link (A-37) | Q | — | opt | `DOCUMENTS_REQUESTED` (derived) |
| 9 | `POST /suppliers/{id}/change-status` | masters | supplier status change | Q+CA | yes | opt | `SUPPLIER_STATUS_CHANGED` |
| 10 | `POST /contacts/{id}/disable` | masters | contact inactive; revoke links/sessions (hook) | Q | yes | opt | `CONTACT_DISABLED` (derived) |
| 11 | `POST /contacts/{id}/replace` | masters | new contact; old disabled + `replaced_by_contact_id`; revoke; reassign open SCARs (new links) | Q | yes | opt | `CONTACT_REPLACED` (derived) |
| 12 | `POST /supplier-access/{token}/verify-otp` | supplier_access | path kept verbatim; browser sends `{token}` = `current` and is authenticated by `ql_pre`; raw tokens in the path are rejected (A-85). Verify OTP (failure → `otp_failed_count` + 1) → create `supplier_sessions` row, set `ql_sup` cookie; marks channel verified | public (token) | — | — | `SUPPLIER_SESSION_STARTED` (derived) |
| 13 | `POST /scars/{id}/issue` | scar | DRAFT → ISSUED; severity, due dates; the notification send job creates one magic link per message (M3) | Q | — | opt | `SCAR_ISSUED` |
| 14 | `POST /scars/{id}/add-ncr` | scar | link NCR (related); NCR → LINKED_TO_SCAR | Q | — | opt | `SCAR_NCR_LINKED` (derived) |
| 15 | `POST /scars/{id}/accept` | scar | (RESPONSE_SUBMITTED →) UNDER_REVIEW → ACCEPTED; review row; `accepted_at` | Q | — | opt | `SCAR_ACCEPTED` |
| 16 | `POST /scars/{id}/send-back` | scar | UNDER_REVIEW → SENT_BACK; review row with comment; revision + 1 on restart | Q | comment required | opt | `SCAR_SENT_BACK` |
| 17 | `POST /scars/{id}/cancel` | scar | DRAFT/ISSUED → CANCELLED; revoke links; linked NCRs → AWAITING_SCAR (A-15) | Q | yes | opt | `SCAR_CANCELLED` (derived) |
| 18 | `POST /effectiveness/{id}/extend` | effectiveness | pending, new window, `extensions + 1` (≤ 2) | Q | yes | opt | `EFFECTIVENESS_EXTENDED` |
| 19 | `POST /effectiveness/{id}/close-no-data` | effectiveness | result `closed_no_data`; effectiveness calls `scar.service.close_after_effectiveness` in the same transaction (SCAR → CLOSED, NCRs → CLOSED, links revoked) | Q | yes | opt | `EFFECTIVENESS_CLOSED_NO_DATA` |
| 20 | `POST /write-offs` | finance | write-off against one allocation | Q (approver field must be `+CA`; if caller is not the approver → 403) | yes | required | `DEBIT_WRITTEN_OFF` |
| 21 | `POST /certificates/{id}/approve` | documents | PENDING_REVIEW → APPROVED (reviewed fields); previous current → SUPERSEDED; requirement current updated | Q | — | opt | `CERTIFICATE_APPROVED` (derived) |
| 22 | `POST /certificates/{id}/reject` | documents | PENDING_REVIEW → REJECTED; requirement per §7.4 (first-time → REQUESTED new due_at; renewal → `renewal_due_at` reset) | Q | yes | opt | `CERTIFICATE_REJECTED` (derived) |
| 23 | `POST /debit-notes/{id}/record-recovery` | finance | recovery + pro-rata allocations (or manual override) | Q | — | required | `DEBIT_RECOVERED` |
| 24 | `POST /imports/{batch}/confirm` | imports | confirm (incl. explicit partial confirmation flag) → enqueue import job | Q | — | required | `IMPORT_CONFIRMED` (derived) |

Count check: 24 rows; each path string is identical to §24.2.

## 3. Additional commands derived from §7 state machines and module specs

Each row cites the § that requires the state change. No feature beyond the blueprint.

### 3.1 Platform / auth (§2.2, §6.1, §21.1)

| Endpoint | Derived from | Effect | Perm |
| --- | --- | --- | --- |
| `POST /auth/login` | §21.1 | email + password → session cookie; rate limited | public |
| `POST /auth/logout` | §21.1 | delete session | any user |
| `POST /auth/password-reset/request` | PHASES P01 | email OTP (Redis, TTL) | public, rate limited |
| `POST /auth/password-reset/confirm` | PHASES P01 | set `password_hash` | public (OTP) |
| `POST /users` · `POST /users/{id}/update` · `POST /users/{id}/deactivate` | §6.1 C1 | user admin incl. role, `can_approve`, `plant_ids` | A |
| `POST /plants` · `POST /plants/{id}/update` | §6.1 C1 | plant admin | A |
| `POST /tenant/settings/update` | §6.1 settings | SLA hours, default PPM target, min samples, score weights (future periods only, §14.5) | A |

### 3.2 Masters (§6.2, §8 C2, §21.5)

| Endpoint | Derived from | Perm |
| --- | --- | --- |
| `POST /suppliers` · `POST /suppliers/{id}/update` · `POST /suppliers/{id}/archive` | §6.2, §7.5 | Q |
| `POST /suppliers/{id}/contacts` (create) · `POST /contacts/{id}/update` · `POST /contacts/{id}/set-quality-contact` | §8 C2 | Q |
| `POST /contacts/{id}/verify/start` · `POST /contacts/{id}/verify/confirm` (OTP to mobile/email) | §8 C2 | Q |
| `POST /contacts/{id}/consents` (record opt-in/out per channel) | §17.3 | Q |
| `POST /contacts/{id}/anonymise` | §21.5 | A |
| `POST /customers` · `/customers/{id}/update` · `/customers/{id}/archive` | §6.2 | Q |
| `POST /parts` · `/parts/{id}/update` · `/parts/{id}/archive` | §6.2 | Q |
| `POST /customer-parts` · `/customer-parts/{id}/archive` | §6.2 | Q |
| `POST /supplier-parts` · `/supplier-parts/{id}/update` (incl. `ppm_target`) · `/supplier-parts/{id}/archive` | §6.2, §14.4 | Q |
| `POST /defect-codes` · `/defect-codes/{id}/update` · `/defect-codes/{id}/deactivate` | §6.3 "editable by Admin" | A |
| `POST /document-requirements` · `/document-requirements/{id}/update` | §8 C10 "editable by Admin" | A |

### 3.3 Imports (§8 C3)

| Endpoint | Effect | Perm |
| --- | --- | --- |
| `POST /imports` | create batch (entity, file upload via signed URL key); file-hash duplicate warning in response | Q |
| `POST /imports/{batch}/map` | save mapping (saved per tenant) | Q |
| `POST /imports/{batch}/validate` | enqueue validation → preview (errors, duplicates, unmapped) | Q |
| `POST /imports/{batch}/cancel` | status cancelled | Q |

### 3.4 Receipts and defect events (§8 C4, §11, §14.5)

| Endpoint | Derived from | Perm | Idem. |
| --- | --- | --- | --- |
| `POST /receipts` (manual entry) | §8 C4 | Q | required |
| `POST /receipts/{id}/correct` (qty/date correction with reason; listed in "Corrections to earlier periods") | §14.5, §7.5 | Q+CA | opt |
| `POST /defect-events` (manual rejection without NCR, attributed with code) | §11.2 | Q | required |
| `POST /defect-events/{id}/link-receipt` | §11.4 (A-24) | Q | opt |

### 3.5 NCR (§7.1, §8 C5, §10)

| Endpoint | Derived from | Effect | Perm |
| --- | --- | --- | --- |
| `POST /ncrs/{id}/photos` | §8 C5 | register uploaded photo key | Q |
| `POST /ncrs/{id}/close` | §7.1 MONITOR → CLOSED, LOCAL_CLOSE → CLOSED | reason required; cost-line warning (A-22) | Q |
| `POST /ncrs/{id}/costs` | §8 C5, §10 | add exposure line | Q |
| `POST /ncr-costs/{id}/correct` | §7.5, §10 | amount/recoverable change with reason; DB guards against allocations | Q+CA |

### 3.6 SCAR (§7.2, §9 C6–C7)

| Endpoint | Derived from | Effect | Perm |
| --- | --- | --- | --- |
| `POST /scars` | §7.2 DRAFT | create draft from NCR(s) (first = primary) | Q |
| `POST /scars/{id}/start-review` | §7.2 RESPONSE_SUBMITTED → UNDER_REVIEW (A-27) | optional; accept/send-back apply it implicitly | Q |
| `POST /scars/{id}/link-related-ncr` | §9 C8 "may link it manually, with reason" | relationship `related`, reason | Q |
| `POST /scars/{id}/reopen` | §7.5 closed SCAR corrections (A-35) | CLOSED → REOPENED | Q+CA |
| `POST /scars/{id}/resend-link` | §9 C7 | re-sends the notification to the current quality contact; the send job revokes the old link(s) and creates new ones (M3) | Q |
| `POST /magic-links/{id}/revoke` | §9 C7 "manual revoke" | revoke + sessions | Q |

### 3.7 Finance (§10)

| Endpoint | Derived from | Effect | Perm | Idem. |
| --- | --- | --- | --- | --- |
| `POST /debit-notes` | §10 | create with full allocations in one call (Σ = amount, DB-deferred check) | Q | **required** (§22.2 request ID) |
| `POST /debit-notes/{id}/accept` | §6.3 status `accepted` (A-30) | raised/disputed → accepted | Q | opt |
| `POST /debit-notes/{id}/dispute` | §6.3 status `disputed` (A-30) | raised/accepted → disputed | Q | opt |
| `POST /debit-note-allocations/{id}/change` | §10 "changing an allocation after recovery requires a command with reason" (A-40) | amount change; all money invariants rechecked | Q+CA | opt |

### 3.8 Documents (§7.3, §7.4, §8 C10)

| Endpoint | Derived from | Effect | Perm |
| --- | --- | --- | --- |
| `POST /documents` | §8 C10 internal upload | register uploaded file → scan → extraction job | Q |
| `POST /certificates/{id}/update-fields` | §20.2 human review | reviewer edits fields while pending; stored in `ai_extractions.corrected_fields` | Q |
| `POST /supplier-requirements/{id}/request-renewal` | §7.4 "or an SQE asks for a replacement" | set renewal_requested_at/renewal_due_at, send link | Q |
| `POST /certificate-exceptions` | §13 (R1.1 UI; endpoint built in P10) | create exception ≤ 90 days | Q+CA |

### 3.9 Tasks, reports, risk (§6.5, §15.5, §16)

| Endpoint | Derived from | Perm |
| --- | --- | --- |
| `POST /tasks/{id}/complete` | §6.5 tasks.status | Q |
| `POST /reports/monthly-quality` (`{plant_id, period}`) → `202 {report_key}` | §16 C14 (PDF in worker, §22) | Q |
| `POST /reports/supplier-card` (`{supplier_id, period, include_internal: bool}`) → `202` | §16 C14 | Q |
| `POST /reports/certificate-compliance` (`{supplier_ids?}`) → `202` | PHASES P03 / §26.3 hook | Q |
| `POST /risk-overrides` | §15.5 (built in P10) | Q+CA |

### 3.10 Webhooks (§17.3, §17.4)

| Endpoint | Effect | Auth |
| --- | --- | --- |
| `POST /webhooks/whatsapp` | delivery status → `messages.status`; inbound STOP/UNSUBSCRIBE → opt-out (A-67); verification `GET` handshake | provider signature |
| `POST /webhooks/email` | delivery/bounce/complaint → `messages.status` | provider signature |

## 4. Supplier-facing endpoints (§9 C7, §21.2; ADR-009)

Module placement (M4): `/supplier-access/*`, `/supplier/session`, `/supplier/logout` → `supplier_access`; `/supplier/scar/*` → `scar`; `/supplier/requirements`, `/supplier/documents/*` → `documents`. All use `supplier_access.service.require_supplier_session(purpose)`. Requests run with the supplier GUCs and scoped RLS (DATA_MODEL.md §0.5). `/s/*` paths and the token segment are never logged.

No supplier route takes an object id: the object comes from the session. Response models are dedicated allow-list
schemas (`Supplier*View`), never internal schemas.

| Endpoint | Auth | Effect |
| --- | --- | --- |
| `POST /supplier-access/exchange` (body `{token}`) | token in body; called only by the Next.js `/s/{token}` route handler over the private network | returns the signed pre-OTP handle; the handler sets `ql_pre` and redirects `303 → /s`; sets `opened_at` first time |
| `GET /supplier-access/{token}` with `{token}` = `current` | `ql_pre` | link status only: `{purpose, customer_company_name, masked_destination, otp_channel}`; sets `opened_at` first time; no object details before OTP |
| `POST /supplier-access/{token}/request-otp` with `{token}` = `current` | `ql_pre` | send OTP (rate limited per link and per IP; A-78) |
| `POST /supplier-access/{token}/verify-otp` | `ql_pre` | §24.2 #12 |
| `GET /supplier/session` | S | `{purpose, expires_at, language_hint}` |
| `GET /supplier/scar` | S (scar_response) | `SupplierScarView` |
| `POST /supplier/scar/response/draft` | S | upsert draft for current revision; first call sets `first_response_at` + ISSUED/SENT_BACK/REOPENED → RESPONSE_STARTED (A-26) |
| `POST /supplier/scar/response/submit` | S | complete D3–D7 → RESPONSE_SUBMITTED; first time sets `final_response_at` | 
| `POST /supplier/scar/evidence/upload-url` → `POST /supplier/scar/evidence` | S | signed PUT URL, then register evidence for open revision |
| `GET /supplier/scar/messages` | S | thread: outbound messages for this SCAR to this contact + send-back comments (A-33) |
| `GET /supplier/requirements` | S (document_upload) | requested / renewal-open requirements of this supplier: `{doc_type, due_at}` only |
| `POST /supplier/documents/upload-url` → `POST /supplier/documents` | S | upload against a listed requirement → document `pending_scan` |
| `POST /supplier/logout` | S | revoke session |

### 4.1 Field exposure — `SupplierScarView` (allow-list)

| Exposed (§9 C7 "sees") | Fields |
| --- | --- |
| SCAR number | `scar_no` |
| Customer company | `tenant.name` (DESIGN_SPEC supplier 8D header) |
| Part | `part_no`, `part_name`, `part_revision` (per linked NCR) |
| Defect description | NCR `description`, defect code `name`, `defect_category` |
| Photos | signed GET URLs (≤ 15 min) for linked NCR photos |
| Quantities | per linked NCR: `qty_checked`, `qty_rejected` |
| Due dates | `containment_due_at`, `final_due_at` |
| D3–D7 form | own `scar_responses` (all revisions) |
| Evidence | own `scar_evidence` |
| Review comments addressed to them | `scar_reviews.comment` where `decision = send_back` (A-32) |
| Message thread | per A-33 |
| Status | supplier-facing subset: `awaiting_response`, `draft_saved`, `submitted`, `sent_back`, `accepted`, `closed` |

| Never exposed (§9 C7 "never sees", §21.2) | Enforcement |
| --- | --- |
| risk, score, costs, debit amounts, internal comments, activity log | not in schema (SCH) + default-deny `p_supplier_deny` on those tables (DB, DATA_MODEL.md §0.5) |
| other NCRs / SCARs / suppliers | no id parameters; queries filter by session object |
| severity, plant, NCR numbers, internal user names, `is_repeat`, disposition | not in §9 C7 "sees" list → excluded (A-82) |

Contract test: `test_supplier_scar_view_schema_has_no_internal_fields` asserts the OpenAPI schema property set equals the allow-list.

## 5. Query endpoints per module (all `GET`, keyset-paginated lists)

| Module | Endpoint | Notes / sorts | Perm |
| --- | --- | --- | --- |
| core | `/me` | user, role, can_approve, plants | any |
| core | `/users`, `/plants`, `/tenant/settings` | | A (users), any (plants) |
| masters | `/suppliers` (`q`, `status`, `category`, `archived`) | sorts: `name`, `code`, `updated_at` | Q,V |
| masters | `/suppliers/{id}` | | Q,V |
| masters | `/suppliers/{id}/contacts`, `/contacts/{id}` (incl. consents) | | Q,V |
| masters | `/customers`, `/parts`, `/parts/{id}`, `/supplier-parts`, `/customer-parts`, `/defect-codes` | `?recent_for_part=` for capture | Q,V |
| imports | `/imports`, `/imports/{batch}`, `/imports/{batch}/preview`, `/imports/{batch}/records` | | Q |
| imports | `/imports/{batch}/report.xlsx` | export (logged) | Q |
| receipts | `/receipts` (`supplier_id`, `part_id`, `plant_id`, `grn_no`, `from`, `to`) | sort `grn_date` | Q,V |
| receipts | `/receipts/lookup?grn_no=` | GRN scan prefill (§8 C5) | Q |
| receipts | `/defect-events?status=unattributed` | attribution queue | Q,V |
| receipts | `/defect-events/{id}/suggestions` | "same rejection" candidates (§11.3) | Q |
| receipts | `/receipts/{id}/rejections` | attributed / unattributed / canonical / unreconciled (§11.4) | Q,V |
| ncr | `/ncrs` (`status`, `severity`, `supplier_id`, `plant_id`, `from`, `to`), `/ncrs/{id}` | | Q,V |
| ncr | `/ncrs/{id}/link-suggestions` | open SCAR with same signature (§9 C6) | Q |
| ncr | `/ncrs/{id}/decision-recommendation` | gate recommendation (§9 C6) | Q |
| scar | `/scars` (`status`, `due_status`, `supplier_id`), `/scars/{id}` (case page payload: NCRs, revisions, reviews, costs, debit notes, effectiveness, messages, history) | `due_status` computed | Q,V |
| scar | `/scars/{id}/responses/{revision}` | | Q,V |
| effectiveness | `/effectiveness?result=pending&older_than_days=90`, `/effectiveness/{id}` | | Q,V |
| finance | `/ncr-costs?ncr_id=`, `/debit-notes`, `/debit-notes/{id}` (allocations, balances) | | Q,V |
| finance | `/metrics/exposure/cohort?plant_id&period` · `/metrics/exposure/cash?plant_id&period` | two views never mixed | Q,V |
| documents | `/documents`, `/documents/{id}`, `/certificates?review_status=pending_review`, `/certificates/{id}` (with `validity` computed) | | Q,V |
| documents | `/suppliers/{id}/requirements` (status, computed compliance/overdue/exception) | | Q,V |
| documents | `/documents/{id}/download-url` | signed ≤ 15 min; logged | Q (V denied, A-70) |
| scoring | `/metrics/suppliers/{id}?plant_id&period` · `/metrics/plants/{id}?period` | each metric: value, sample, coverage, freshness, provisional, `how` | Q,V |
| scoring | `/metrics/{metric}/explain?scope…` | "How this was calculated": formula, inputs, exclusions, record ids | Q,V |
| scoring | `/scores?plant_id&period` (ranking: measured + insufficient-data lists) · `/suppliers/{id}/scores` | | Q,V |
| risk | `/suppliers/{id}/risk` (system score, level, reasons, trend, override) · `/risk?level=high` | | Q,V |
| notifications | `/messages?object_type&object_id`, `/notifications/in-app` | | Q,V |
| reports | `/my-work` (counts + grouped queue, §16) · `/my-work/{group}` | budget < 500 ms server (PHASES P08) | Q,V |
| reports | `/suppliers/{id}/overview` (Supplier 360) | | Q,V |
| reports | `/reports/{report_key}` → `{status, download_url?}` | | Q,V |
| reports | `/exports/{list}.xlsx?<same filters as list>` | permission-checked, logged (§16 C14) | Q (V denied, A-70) |
| files | `/files/upload-url` (`{purpose, content_type, size}`) → `{key, url, expires_at}` | ≤ 15 min, size ≤ 20 MB | Q |
| health | `/healthz` (process up, no deps; **load-balancer target check**) · `/readyz` (DB `SELECT 1`, Redis `PING`, migrations at head; deploy gate + canaries) | unversioned, no auth | public |

### 5.1 Named list sorts (m5)

Every keyset sort is backed by the named index in DATA_MODEL.md §0.7; `sort` values not listed are rejected with `400`.

| Endpoint | `sort` (default first) | Order | Index |
| --- | --- | --- | --- |
| `/suppliers` | `name`, `code`, `updated_at` | asc, asc, desc | `ix_suppliers_name`, `ix_suppliers_code`, `ix_suppliers_updated` |
| `/parts` | `part_no` | asc | `ix_parts_part_no` |
| `/receipts` | `grn_date` | desc | `ix_receipts_plant_grn_date` |
| `/defect-events?status=unattributed` | `created_at` | asc | `ix_defect_events_unattributed` |
| `/ncrs` | `detected_at` | desc | `ix_ncrs_plant_detected` / `ix_ncrs_status_detected` (with `status`) |
| `/scars` | `final_due_at` | asc | `ix_scars_status_due`; `ix_scars_supplier_status` with `supplier_id` |
| `/effectiveness?result=pending` | `start_at` | asc | `ix_effectiveness_pending_start` |
| `/debit-notes` | `dn_date` | desc | `ix_debit_notes_supplier_date` |
| `/certificates?review_status=pending_review` | `created_at` | asc | `ix_certificates_review_queue` |
| `/documents` | `doc_type` | asc, version desc | `ix_documents_supplier_type` |
| `/imports` | `created_at` | desc | `ix_import_batches_created` |
| `/imports/{batch}/records` | `row_number` | asc | `ix_import_records_batch_row` |
| `/messages` | `created_at` | desc | `ix_messages_object` |
| `/notifications/in-app` | `created_at` | desc | `ix_messages_in_app` |
| `/risk?level=` | `system_score` | desc | `ix_risk_current_level` |
| `/scores` | `total_score` | desc nulls last (measured list; insufficient-data list separate) | `ix_scores_plant_period` |

## 6. Rate limits (Redis counters; ADR-008, ADR-009)

| Target | Limit (default, configurable) |
| --- | --- |
| `POST /auth/login` | 5 failures / 15 min per email and per IP |
| `POST /auth/password-reset/request` | 3 / hour per email |
| `POST /supplier-access/{token}/request-otp` | 3 / hour per link; 10 / hour per IP (D-6, A-78) |
| `POST /supplier-access/{token}/verify-otp` | 5 attempts per OTP; 30 / hour per IP; 10 failures per link (persisted in `magic_links.otp_failed_count`, A-86) → link revoked `otp_attempts_exceeded` (A-36, A-78) |
| `POST /supplier-access/exchange`, `GET /s/*` | 30 / min per IP (WAF + app) |
| exports | 20 / hour per user |
