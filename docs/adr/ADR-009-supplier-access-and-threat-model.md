# ADR-009 — Supplier access (magic link + OTP + scoped session) and threat model

- Status: Proposed
- Spec: §4.2, §8 C2 (180-day re-verification, replace/disable), §9 C7, §21.2, §21.5

## Context
Suppliers never have accounts. Access lifecycle (§9 C7): 32-byte token, hash only, link via WhatsApp + email, OTP to
the contact's verified mobile (or email), session scoped to ONE object for 7 days, link re-openable for 30 days with a
new OTP, revocation on contact disable/replace, SCAR close/cancel, manual revoke. Pages must work on low-end Android over 3G.

## Decision
| Element | Design |
| --- | --- |
| Token | `secrets.token_bytes(32)`, URL `https://<app>/s/{base64url(token)}`; DB stores `sha256(token)` (`bytea`, unique). Plaintext exists only in memory of the send job (M3) |
| Link creation (M3) | Not in the issuing command. The notification send job, in one transaction, revokes any previous link of that message (`revoked_reason='reissued'`), inserts the new `magic_links` row, and sets `messages.magic_link_id` (A-87). After commit it calls the provider with the token held in memory. A send that is lost or retried therefore always re-issues a new link and revokes the old one. One link per message (WhatsApp and email each carry their own); both are scoped to the same object |
| Token leaves the URL immediately (D-4) | `GET /s/{token}` is a Next.js server route handler that renders no HTML. It POSTs the token in a request body over the private network to `POST /api/v1/supplier-access/exchange` and receives a signed pre-OTP handle `(tenant_id, magic_link_id, exp = 15 min)`. It then sets HttpOnly cookie `ql_pre` (`Secure; SameSite=Lax; Path=/; Max-Age=900`) and answers `303 → /s` with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`. The token is never in browser history after the redirect, never in a Referer header, and never available to JS |
| Logging of `/s/*` (D-4) | Edge: CloudFront has standard logging disabled; real-time logs are attached only to cache behaviours other than `/s/*`; WAF logging uses `RedactedFields: uri_path`. ALB access logs are disabled (CloudFront logs cover the edge). App: the access-log middleware drops the path for `/s/*` and replaces the token segment of `/api/v1/supplier-access/*` with `:token`. Next.js does not log request paths |
| Link scope | `scar_response` → one SCAR; `document_upload` → one supplier's requested requirements (A-37) |
| Link validity | 30 days (`expires_at`), reusable with fresh OTP; revoked per §9 C7 and after 10 failed OTP verifications (A-36, A-78) |
| OTP | 6 digits, `secrets.randbelow`, argon2-hashed in Redis `otp:{link_id}`, TTL 10 min, 5 attempts per OTP, 3 sends per hour per link; per IP: request-otp 10/hour, verify-otp 30/hour (D-6). Failed verifications also increment `magic_links.otp_failed_count` in Postgres (A-86), so the 10-failure revocation survives Redis loss. Sent to the contact's mobile (WhatsApp/SMS), else email; if the channel was unverified, success sets `verified_*_at` (A-38) |
| 180-day rule | link issue refused for contacts with `verified_*_at` older than 180 days; SQE task to re-verify (§8 C2) |
| Pre-OTP endpoints | authenticated by `ql_pre`; the §24.2 path `POST /supplier-access/{token}/verify-otp` is kept verbatim with `{token}` = literal `current` (resolved from `ql_pre`); raw tokens in that path are rejected (SPEC-GAP A-85) |
| Session | `supplier_sessions` row (`otp_verified_at`, `expires_at ≤ +7 d`, ip, ua); cookie `ql_sup` = HMAC-SHA256-signed `(tenant_id, session_id)`, `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/supplier` |
| Per-request check | signature valid → set GUCs (`tenant_id`, `actor_type='supplier_session'`, `actor_id`, `supplier_session_id`, `magic_link_id`, `scope_object_*`, `supplier_id`) → session not revoked/expired → link not revoked/expired → contact active → object from session |
| Routes | `/supplier/*` routes take **no object id**; responses use allow-list schemas (API.md §4.1). Module placement (M4): `supplier_access` owns exchange/OTP/session and exports `require_supplier_session(purpose)`; `/supplier/scar/*` routes live in `scar`, `/supplier/requirements` and `/supplier/documents/*` in `documents` |
| DB defence | deny-by-default RLS: every table has `p_supplier_deny` unless it opts in via `enable_supplier_scoped_rls` with an explicit predicate on the supplier GUCs (DATA_MODEL.md §0.5 lists all 19 such tables plus `idempotency_keys`); no supplier DELETE; `activity_log`/`outbox_events` insert-only (ADR-004) |
| Errors | expired/revoked/used-up/disabled → one generic `410 link_invalid` page with "ask your customer for a new link" |
| Uploads | signed PUT to quarantine, ≤ 20 MB, PDF/JPG/PNG; scanned before visible (ADR-011) |
| Rendering | supplier-entered text rendered as text (React escaping); no HTML/Markdown |
| Audit | every supplier command writes `activity_log` with `actor_type='supplier_session'`, `actor_id=contact_id`, `session_id`, ip |

## Threat model (STRIDE)
| Threat | Vector | Mitigation | Test |
| --- | --- | --- | --- |
| **S**poofing | Forwarded/leaked link used by someone else | OTP to contact's own channel; link alone shows only masked destination | `test_session_not_created_without_otp` |
| Spoofing | Phone number reassigned to a new person | 180-day re-verification; contact replace revokes | `test_link_not_sent_to_contact_unverified_for_180_days` |
| Spoofing | OTP brute force (10⁶ space) | 5 attempts/OTP, 3 sends/h, 10 failures → link revoked; constant-time compare | `test_otp_rate_limited`, `test_link_revoked_after_failed_otp_limit` |
| **T**ampering | Edit cookie to another session/tenant | HMAC signature; session row must exist under that tenant and be active | `test_tampered_supplier_cookie_rejected` |
| Tampering | Modify a submitted 8D revision | submitted rows immutable (DB trigger) | `test_submitted_revision_update_rejected_db` |
| Tampering | Malicious file (malware, polyglot) | magic-byte check, size cap, virus scan, quarantine bucket, `Content-Disposition: attachment` on download | `test_unscanned_file_not_downloadable` |
| **R**epudiation | Supplier denies submission | activity_log with session id, ip, UA, timestamps; revisions kept | `test_supplier_submit_writes_activity_log_with_session_and_ip` |
| **I**nformation disclosure | IDOR to other SCARs/suppliers | no ids in routes; scope from session; 404 | `test_supplier_session_cannot_read_other_scar` |
| Information disclosure | Internal costs, risk, comments | allow-list schemas + default-deny `p_supplier_deny` (scoped RLS only on listed tables) | `test_supplier_scar_view_schema_has_no_internal_fields` |
| Information disclosure | Token in logs/referrer/history | immediate exchange to HttpOnly `ql_pre` + 303 to `/s`; edge and app do not log `/s/*`; `Referrer-Policy: no-referrer` | `test_access_log_redacts_magic_link_token`, `test_link_open_exchanges_token_for_cookie_and_redirects` |
| Information disclosure | IDOR via DB if app scope check is wrong | scoped RLS predicates | `test_supplier_rls_denies_unlisted_tables_db`, `test_supplier_rls_scar_scope_db` |
| Information disclosure | Token guessing | 256-bit tokens; lookup by hash | `test_magic_link_token_has_32_bytes_entropy` |
| **D**enial of service | Flood OTP sends (cost, spam) or distributed guessing | per-link and per-IP limits on request-otp and verify-otp; persisted failure count; WAF rate rule | `test_otp_rate_limited`, `test_otp_per_ip_limit`, `test_otp_failure_count_persisted_in_db` |
| Tampering | Prompt injection in 8D text affecting AI review | AI output advisory only, schema-constrained, rendered escaped (ADR-012) | `test_8d_assist_output_is_advisory_and_escaped` |
| **E**levation of privilege | Supplier cookie on internal routes | separate cookie name/path; internal routes require `ql_session` | `test_supplier_cookie_rejected_on_internal_routes` |
| Elevation | Session outlives contact disable/replace or SCAR close | revocation hooks in same transaction + per-request contact/link check | `test_disabled_contact_session_fails`, `test_scar_close_revokes_links` |

## Consequences
- OTP and rate-limit state live in Redis; Redis loss only forces a new OTP.
- No "remember device"; every new session requires OTP (§9 C7).

## Revisit when
- Supplier link open → submit conversion (§22.4) < 50% with OTP as the main drop-off point, or
- a large supplier requests a login portal (Part B §29) — new spec section first.
