# QualLoop — Build Phases (R1 → R1.1 → scale)

Every phase follows CLAUDE.md §3: plan → tests first → build → review → independent verification →
fix loop → human gate → commit + tag. `§` = section of `docs/blueprint/Supplier_Quality_OS_Blueprint_FINAL.md`.

A phase is DONE only when every gate item has a named, passing test or a command with real output.
Nothing outside the phase scope may be built early.

| Phase | Name | Main agents | Blueprint |
| --- | --- | --- | --- |
| P00 | Architecture & scaffold | architect, devops | all; §22, §24 |
| P01 | Platform foundation | backend, devops, security | §6.1, §7.5, §21, §22, §24 |
| P02 | Masters & imports | backend, frontend | §6.2, §6.7, §8 C2–C3 |
| P03 | Documents, certificates & AI extraction | backend, data, frontend | §6.4, §7.3, §7.4, §8 C10, §13, §20 |
| P04 | Receipts, NCR & defect events | backend, data, frontend | §6.3, §8 C4–C5, §11 |
| P05 | SCAR, supplier access & notifications | backend, frontend, security | §6.5, §7.1–§7.2, §9 C6–C7, §17 |
| P06 | Effectiveness & money | data, backend, frontend | §9 C8, §10 |
| P07 | Metrics, score & risk | data, backend | §12, §14, §15 |
| P08 | My Work, Case, Supplier 360, reports | frontend, backend | §16, C14, DESIGN_SPEC |
| P09 | Hardening, deployment & pilot readiness | devops, security, all | §20.5, §21, §22.4, §23, §25, §27 |
| P10 | R1.1 (after first pilot plant is live) | all | §5.2, §13, §15.5, §18, §19, §21.3 |
| Scale track | Stage 2 / Stage 3 changes, trigger-driven | architect, devops, data | SCALING.md |

---

## P00 — Architecture & scaffold  (`/architecture`)

**Goal:** a complete, approved architecture and a running empty skeleton. No features.

**Deliverables**
- `docs/understanding.md` — control loop, entities, state machines, invariants with §, ambiguities.
- `docs/architecture/` — ARCHITECTURE.md, DATA_MODEL.md (every §6 table: columns, types, constraints,
  indexes, RLS), INVARIANTS.md (invariant · § · enforcement · test name), API.md (all §24.2 commands +
  queries, error format, keyset pagination, idempotency), SCALING.md (Stage 1/2/3 + triggers), REPO_LAYOUT.md.
- `docs/adr/` — at least: modular monolith; tenancy & RLS (requests, workers, supplier sessions);
  IDs/money/time; outbox & jobs (library choice); metrics engine; supplier access & threat model;
  frontend architecture/tokens/i18n/PWA; storage & signed URLs; AI provider & governance; observability;
  CI/CD & environments; hosting & deployment (India region, managed Postgres/Redis/object storage,
  containers, IaC); backup/restore; security baseline & secrets.
- Scaffold: `/api` (FastAPI app factory, settings, health `/healthz` `/readyz`, structured logging),
  `/web` (Next.js app shell, tokens.ts from DESIGN_SPEC, fonts, i18n setup en/hi), `/infra`
  (docker compose: postgres16, redis, S3-compatible store (SeaweedFS, ADR-020), mailpit), `Makefile` (`up`, `down`, `test`, `lint`, `fmt`,
  `migrate`, `seed`), CI pipeline, pre-commit hooks, `.env.example`, `.gitignore`.
- Alembic baseline with the RLS helper (function to set `app.tenant_id`, policy template).
- `docs/build/STATUS.md`, `OPEN_QUESTIONS.md`, `docs/CHANGELOG.md` initialised.

**Gate**
1. `make up` starts all services; `/healthz` and web home return 200.
2. CI runs lint, types, tests (a placeholder test), migration up/down/up — all green.
3. Every §6 table appears in DATA_MODEL.md; every invariant from §7, §10, §11, §12, §14, §15 appears in INVARIANTS.md.
4. Every §24.2 command appears in API.md.
5. Human has approved the architecture.

**Commits**: `docs(p00): architecture, ADRs and repo scaffold` → tag `p00-verified` after approval.

---

## P01 — Platform foundation

**Goal:** the secure multi-tenant core every module relies on.

**Scope**
- Tables: `tenants`, `plants`, `users`, `activity_log`, `outbox_events` (§6.1). UUIDv7, audit columns, RLS.
- Auth: email+password (argon2/bcrypt), sessions, password reset by email OTP, login rate limit. (Google login deferred to R1.1 — human decision 2026-10-03, A-46.)
- Roles: admin / quality / viewer + `can_approve` flag (§2.2). Permission decorator for commands.
- Tenant context: middleware sets `app.tenant_id` per request; worker job wrapper sets it per job.
- Command framework: base command handler doing authorize → validate → mutate → activity_log
  (before/after/reason/actor_type/session/ip) → outbox event, in one transaction.
- Outbox dispatcher worker: polling with `FOR UPDATE SKIP LOCKED`, retries with backoff, dead-letter after 5,
  `processed_at`, `attempts`, `last_error`.
- Idempotency-key support for command endpoints.
- Signed-URL file service (upload/download), content-type & size validation, virus-scan hook (ClamAV container).
- Settings per tenant (json: SLA hours, PPM target default, minimum samples, score weights) (§6.1).
- Error format, request_id, structured logs, OpenTelemetry tracing.

**Mandatory tests**
- Tenant A cannot read/write Tenant B rows through API, raw ORM session, or worker (§21.2).
- Command writes activity_log + outbox in the same transaction; failure rolls back both.
- Outbox: event processed exactly once under two concurrent workers; retries then dead-letter.
- Viewer cannot call any command; `can_approve` required where flagged.
- Signed URL expires (≤ 15 min); unauthorised user cannot download.
- Migrations up/down/up.

**Gate**: all tests green; security-reviewer has no Critical/High; coverage ≥ 90% on core.

**Commits**: `test(p01): …` → `feat(p01): platform foundation` → `fix(p01): …` → `docs(p01): …`; tag `p01-verified`.

---

## P02 — Masters & imports

**Goal:** a customer's suppliers, contacts, parts and mappings can be loaded from messy Excel safely.

**Scope**
- Tables (§6.2): `suppliers` (status + reason fields), `supplier_contacts` (lifecycle fields),
  `contact_consents`, `customers`, `parts`, `customer_parts`, `supplier_parts` (with `ppm_target`).
- Tables (§6.7): `import_batches`, `import_records`.
- Import engine (§8 C3): upload → detect → map (saved per tenant) → validate → preview → errors/duplicates/
  unmapped → confirm → import → reconciliation report (downloadable Excel with reason per row).
  File-hash duplicate warning; row hash + natural keys; duplicates reported, never merged.
- Contact lifecycle (§8 C2): verify mobile by OTP, disable (reason), replace (revokes the old contact's
  links/sessions — implement the revocation hook now, links come in P05), re-verify after 180 days.
- Supplier status command (§15.6) with reason and `can_approve` — status only, no risk yet.
- UI: Suppliers list (search, filter, keyset pagination), Supplier create/edit, Contacts, Parts,
  Import wizard with preview and reconciliation report.

**Mandatory tests**
- Same 5,000-row supplier/receipt-style file imported twice → 0 duplicates created, report shows duplicates (§8 C3).
- Duplicate supplier by GSTIN, and by name + city, reported not merged.
- Partial import requires explicit confirmation.
- Contact disable/replace → future revocation hook called; replaced contact keeps history.
- Status change without reason or without `can_approve` rejected; activity_log has before/after.
- CSV/Excel formula injection neutralised in exported reports.

**Gate**: tests green; import of 5,000 rows completes < 60 s locally; UI E2E: import wizard happy path + error path.

---

## P03 — Documents, certificates & AI extraction

**Goal:** the sales hook — upload a supplier's certificates, extract fields, review, and see compliance.

**Scope**
- Tables (§6.4): `documents`, `certificates` (review status only), `document_requirements` (template, grace_days),
  `supplier_requirements` (lifecycle + renewal fields), `certificate_exceptions` (table only; UI in P10),
  `ai_extractions`.
- Computed validity (§7.3): valid / expiring_60 / expiring_30 / expiring_7 / expired — never stored.
- Requirement lifecycle (§7.4): first-time vs renewal paths; rejected renewal keeps `current_certificate_id`;
  `status = approved` ≠ compliant; exceptions computed from `certificate_exceptions`.
- Supplier requirements auto-created on supplier create / category change; bulk "request all missing".
- AI extraction worker (§20.2): OCR/text → classify → strict-JSON extraction → validation rules → per-field
  confidence & source span → human review queue. Provider behind `app/ai/providers/`. Store model,
  prompt version, extraction version, source hash, latency, cost.
- AI benchmark harness (§20.5): runs a labelled set (start with a seeded sample; the 200-certificate set is
  collected during pilots) and reports per-field accuracy.
- Certificate review UI: side-by-side document + extracted fields with confidence, approve/reject with reason.
- Certificate compliance report PDF (first version of §16 C14) — the free report used in sales.
- Supplier-facing document upload page is built in P05 (needs magic links). In P03 internal users upload.

**Mandatory tests**
- Validity changes across 60/30/7/0-day boundaries with no job run (freeze time).
- New supplier with requirements not requested → no `CERT_MISSING` condition (risk itself comes in P07; test the
  condition function now).
- Requirement requested and past due_at → overdue condition true.
- Rejected renewal upload while current certificate valid → still compliant; current_certificate_id unchanged.
- Rejected first-time upload → requirement missing after new due date.
- Requirement REQUESTED and past `due_at` with nothing uploaded → status stays REQUESTED, overdue is computed (`test_requested_requirement_stays_requested_when_overdue`).
- SQE asks for a replacement while the current certificate is valid → `renewal_requested_at` / `renewal_due_at` set, status stays APPROVED (`test_sqe_replacement_request_sets_renewal_fields`).
- Compliance % formula (§12) including pending exclusion.
- AI never sets certificate status; AI outage → manual entry still works.

**Gate**: tests green; 50 mixed sample certificates processed end to end; compliance PDF generated from seed data.

---

## P04 — Receipts, NCR & defect events

**Goal:** every rejection is captured fast and counted exactly once.

**Scope**
- Tables (§6.3): `grn_receipts` (unique key), `defect_codes` (tenant list, seeded defaults), `defect_events`,
  `defect_event_attributions`, `ncrs` (qty_rejected derived), `ncr_photos`, `ncr_containment`, `ncr_costs`.
- Receipts import (reuse P02 engine) incl. ERP rejection rows → unattributed defect events.
- NCR state machine (§7.1) via commands: create, contain, decide-scar (records the decision; SCAR itself in P05),
  dispose (use-as-is needs `can_approve`), cancel (reason), reopen (reason).
- 30-second capture (§8 C5): photo-first, GRN scan prefill, per-defect qty, severity, customer_disruption;
  `capture_started_at` / `capture_submitted_at`.
- Defect signature (supplier + part + defect code, fallback category); repeat flag (90 days).
- Attribution flow (§11.3): four decisions, suggestion when receipt + qty match, never automatic; every decision
  writes `defect_event_attributions`.
- Canonical vs unreconciled quantity (§11.4) as a data service (metrics use it in P07).
- UI: inspector mobile PWA capture screen (DESIGN_SPEC), NCR list/detail, attribution dialog.

**Mandatory tests**
- ERP + NCR for the same rejection → counted once after attribution.
- ERP + NCR for different defects → both counted.
- Internal (not supplier) decision → excluded.
- Receipt with attributed + unattributed events → canonical = attributed; unreconciled = unattributed (conservative).
- Receipt with only unattributed ERP events → counted in canonical.
- Same receipt file imported twice → no duplicate receipts or defect events.
- Repeat flag uses signature, not just supplier + part.
- Use-as-is without `can_approve` rejected.
- E2E: NCR capture completes in ≤ 30 s scripted path; capture timestamps stored.

**Gate**: tests green; property-based tests on attribution pass; mobile E2E passes at 360 px width.

---

## P05 — SCAR, supplier access & notifications

**Goal:** a supplier with no account answers a real SCAR on a phone, and every message is tracked.

**Scope**
- Tables: `scars` (timing fields per §6.3 definitions), `ncr_scar_links`, `scar_responses`
  (occurrence/escape/systemic causes), `scar_evidence`, `scar_reviews`; (§6.5) `magic_links`,
  `supplier_sessions`, `messages`, `tasks`.
- SCAR decision gate and severity policy (§9 C6): recommendation, SLA in calendar hours, plant timezone.
- SCAR state machine (§7.2) commands: issue, add-ncr, accept, send-back (revision + 1), cancel.
- Supplier access (§9 C7): token hashed, scoped to one object + contact, OTP to verified mobile/email,
  7-day session, 30-day link, revocation on contact disable/replace and SCAR close/cancel; field-level
  exposure rules (supplier never sees costs, risk, internal comments, other objects).
- Supplier 8D form (mobile, en/hi, draft autosave, evidence upload) and supplier document upload page (P03 link-up).
- Notifications (§17): template abstraction, WhatsApp BSP/Cloud API adapter (sandbox in dev), email, in-app,
  optional SMS; consent records and STOP handling; delivery tracking; fallback to email within 15 min on failure.
- Reminders & escalations (§9 C7) as scheduled jobs; daily digest.
- 8D review assist (§20.3) as a worker producing suggestions only.
- UI: SCAR list, basic case review screen (full Case page polished in P08), send-back with comment.

**Mandatory tests**
- Supplier session cannot read any other SCAR, NCR, supplier, cost, risk or internal comment.
- Expired, revoked, and used links fail; disabled contact's sessions fail; OTP rate limited.
- `final_response_at` = first complete D3–D7 submission; later revisions don't move it.
- Send-back creates a new revision; all revisions retained.
- WhatsApp failure → email fallback; opted-out contact gets email only; no duplicate sends on retry.
- Many NCRs → one SCAR; new NCR with same signature suggested for linking.
- AI suggestion never changes SCAR state.

**Gate**: tests green; E2E on a 360 px viewport: open link → OTP → complete 8D in Hindi and English → SQE sends
back → supplier revises → SQE accepts.

---

## P06 — Effectiveness & money

**Goal:** fixes are verified by results, and every rupee is traceable.

**Scope**
- `effectiveness_checks` with signature (§9 C8): min lots AND min days (+ min qty); pass / fail on signature
  match only; unrelated defect doesn't fail; unattributed ERP rejection on a watched receipt holds;
  90-day pending → My Work → Extend (max 2) or Close-no-data (reason) commands.
- Money (§10): `ncr_costs` (exposure lines, recoverable flag), `debit_notes`, `debit_note_allocations`,
  `recoveries`, `recovery_allocations`, `write_offs`.
- Invariants in DB + commands: allocations only to recoverable lines; Σ allocations = debit note amount;
  Σ per cost line ≤ line amount; recovered + written_off ≤ allocation; outstanding never negative;
  pro-rata recovery by remaining outstanding with deterministic rounding.
- KPIs: exposure cohort view and cash view (§10), never mixed.
- UI: cost lines on NCR, debit note create with allocation, record recovery, write-off with reason.

**Mandatory tests**
- Allocation to non-recoverable cost line rejected (DB and API).
- Recovery + write-off exceeding allocation rejected (DB and API).
- One debit note across three NCRs with partial recovery and a write-off — all balances correct.
- Recovery in a later month than exposure: cohort vs cash views correct.
- Effectiveness: unrelated defect on same part → not failed; matching defect → failed + SCAR reopened;
  extend twice then close-no-data; no pass/fail without data.
- Property-based tests on money invariants.

**Gate**: tests green; concurrency test — two simultaneous recoveries cannot breach an allocation.

---

## P07 — Metrics, score & risk

**Goal:** numbers a quality head and an auditor both trust.

**Scope**
- Metrics service (§12): PPM, quantity rejection %, lot rejection rate, unreconciled qty, PPM by defect,
  repeat NCRs, customer disruptions, premium freight, SCAR on-time % with on_time/late/overdue,
  late completions, time to first response / acceptance, document compliance %, recovery %, NCR capture time.
- Trust signals on every metric: sample, coverage, freshness; minimum sample → N/A (§12.1).
- "How this was calculated" payload for every metric (formula, period, inputs, exclusions, source record ids).
- Supplier Quality Score (§14): components, weights, re-weighting for N/A, no total when Quality is N/A,
  grades, targets (tenant default + supplier-part override), monthly immutable snapshots, as-of rule,
  corrections-to-earlier-periods listing.
- Risk engine (§15): rules with windows and params, recomputed nightly and on events, active/cleared risk events,
  `supplier_risk_current` with reasons and trend, overrides table, "suggest on watch" after 2 High months.

**Mandatory tests**
- Every §12 formula with fixed fixtures; insufficient-data cases return N/A.
- SCAR overdue at September month-end then submitted in October: September snapshot unchanged; October shows
  a late completion.
- Data correction made in March for a January receipt: January snapshot unchanged; correction listed.
- Provisional PPM when unreconciled qty > 0.
- Ranking excludes insufficient-data suppliers.
- Risk: each rule fires and clears within its window; reasons reproducible from rule_code + params;
  risk never changes supplier status.
- Performance: metrics for 300 suppliers × 12 months on seed ×10 data within budget.

**Gate**: tests green; data-engineer note maps every formula → code → test.

---

## P08 — My Work, Case, Supplier 360, reports

**Goal:** the product as designed — the screens people live in.

**Scope** (match DESIGN_SPEC and the approved design artifact)
- My Work home: count tiles, grouped queue (overdue SCARs, responses to review, critical NCRs without
  containment, NCRs awaiting SCAR decision, ERP rejections to attribute, certificates ≤ 30 d,
  requirements never requested, effectiveness needing decision), rail (exposure cohort, turned-High-risk, data health summary).
- Supplier Quality Case page: header, 6-step progress, tabs (8D, NCRs, Money, Effectiveness, Messages, History),
  cause cards, AI suggestion box, rail.
- Supplier 360: status vs risk blocks, score with components and coverage, PPM trend with target, risk reasons,
  open cases, documents with validity chips, contact & consent.
- Dashboard panels below My Work; drill-down everywhere; "How this was calculated" drawer.
- Reports (C14): Monthly Supplier Quality Report PDF and supplier report card PDF; Excel exports
  (permission-checked, logged).
- Empty, loading, error, N/A and Provisional states on every screen; en/hi where supplier-facing.

**Mandatory tests**
- Playwright E2E for each screen's primary flow; axe accessibility checks; visual snapshots.
- Every KPI on screen drills to records that sum to the shown number.
- Report PDF numbers equal API metric values for the same period.

**Gate**: ux-reviewer passes all 10 UX rules per screen; E2E green; performance budgets met (My Work < 500 ms server).

---

## P09 — Hardening, deployment & pilot readiness

**Goal:** safe to put a real plant on it.

**Scope**
- Full security test suite (§21.2) in CI; dependency/secret scanning; pen-test checklist; rate limits everywhere.
- Staging and production via IaC in an India region; CI/CD with manual approval to prod; zero-downtime
  migrations policy; feature flags for risky features.
- Observability dashboards and alerts (§22.4); runbooks (deploy, rollback, restore, incident, rotate secrets).
- Backups + PITR; restore drill executed and timed (RPO 24 h / RTO 8 h).
- AI benchmark gates wired into CI for model/prompt changes (§20.5).
- Seed demo tenant (§24.1 rule 6) and onboarding tooling (§23): import templates, 48-hour first dashboard runbook.
- Pilot instrumentation (§25): weekly pilot metrics report incl. "supplier responses without intervention".
- Billing (minimal): plan, active-supplier count per plant, monthly invoice export. Flag SPEC-GAPs for anything more.
- Load test: seed ×10, 50 concurrent users, workers under backlog.

**Gate**: restore drill passed; load test within budgets; no open Critical/High security findings;
human approves go-live for the first pilot plant.

---

## P10 — R1.1 (only after the first pilot plant is live)

Scope (§5.2): data-health screen (§19), supplier response-behaviour metrics (§18), target hierarchy via
`quality_targets`, risk override UI (§15.5), Supplier Quality Evidence Pack export (§21.3), certificate
exception UI (§13), plant holiday calendar for SLAs, Google login for internal users (A-46, human decision 2026-10-03). Each item is its own mini-phase with the same protocol.

---

## Scale track (trigger-driven, never speculative)

Owned by architect + devops + data. Each item starts only when its trigger in `docs/architecture/SCALING.md`
is hit, with an ADR and human approval:
- Partition `activity_log`, `messages`, `outbox_events`, `defect_events` by month.
- Read replica for reporting; move heavy metrics to materialised tables refreshed by workers.
- Dedicated search (OpenSearch) only when Postgres full-text fails budgets.
- Enterprise: SSO/SAML/SCIM, dedicated database per tenant option, multi-plant consolidation,
  SOC 2 / ISO 27001 readiness, data residency guarantees.
- R2 features (PPAP, 4M, deviations, delivery performance) only after ~5 paying plants and a new spec section.
