# Supplier Quality OS — Product Blueprint

**Version:** Final (frozen)
**Owner:** Pankaj Kumar
**Category:** Supplier Quality Control software for Indian manufacturing
**First market:** IATF 16949-certified auto-component manufacturers in Delhi NCR (Gurugram, Manesar, Bawal, Faridabad)

---

## 0. How to use this document

| Part | Content | Use |
| --- | --- | --- |
| **Part A — R1 Build Spec (§1–§27)** | What to build in the first 12–16 weeks, split into **R1 Core** (build from day one) and **R1.1** (after the first pilot) | You + Claude Code. Build only this. |
| **Part B — Roadmap (§28–§31)** | R2 and R3 capabilities, added only when paying customers ask | Roadmap decisions, partner conversations |

**Release labels:** R1 = first release (12–16 weeks), R1.1 = after the first pilot plant, R2 = after ~5 paying plants, R3 = enterprise.

**Rule:** if it is not in Part A, do not build it. The data model is designed so Part B can be added without rewrites.

---

# PART A — R1 BUILD SPEC

## 1. Product thesis

> **Turn a supplier defect from a scattered Excel / WhatsApp / email problem into a traceable quality, corrective-action, financial and risk decision loop.**

**Core promise:** From supplier rejection to verified corrective action — automatically tracked.
**Supporting promise:** Your suppliers don't need another login.
**Economic promise:** Know what supplier defects cost, what was recovered, and which suppliers are getting worse.

### 1.1 What the product is not

Not an ERP, inventory, accounting, MES, generic QMS, document drive, procurement suite or CRM. ERP stays the system of record for purchasing, inventory, finance and goods receipts. This product is the **system of supplier-quality workflow** that ingests and enriches that data.

### 1.2 Claims we make and avoid

| Say | Never say |
| --- | --- |
| "Supports IATF supplier-quality workflows" | "IATF-compliant software" / "Makes you IATF certified" |
| "Continuously preserves supplier-quality evidence for reviews and audits" | "Audit-ready" / "Guaranteed compliance" |
| "Your first supplier-quality dashboard from your own data within 48 hours" | "Fully live in 48 hours" |
| "Covers core supplier-monitoring indicators" | "Covers all OEM customer-specific requirements" |

---

## 2. Customer

### 2.1 Qualify by pain, not by turnover

A plant is a good R1 customer when **most** of these are true:

- IATF 16949 certified (supplier monitoring is an audit topic)
- 50–300 active suppliers
- 1–2 plants, 3–15 people in quality / supplier quality
- Supplier rejections tracked in Excel, registers or WhatsApp
- SCAR / 8D sent by email or WhatsApp with no overdue tracking
- ERP exists (Tally, SAP Business One, homegrown) but has no usable supplier-quality workflow
- Recent pain: a customer complaint traced to a supplier, an audit finding on supplier control, or rising rejections

**Test two bands in discovery** and let evidence decide: (a) Tier-2 / upper Tier-3, ₹50–500 Cr; (b) Tier-1, ₹500–2,000 Cr without a mature QMS.

**Not R1 customers:** OEMs (own portals), plants with full SAP QM or an established QMS in active use, pharma, medical devices, food.

### 2.2 Buyer and users

| Role | Part in the sale | Uses R1 for |
| --- | --- | --- |
| Plant Head / MD | Approves budget | Monthly report, financial exposure |
| Head of Quality | Champion, decides | Supplier ranking, overdue actions, evidence |
| Supplier Quality Engineer (SQE) | Daily user | NCRs, SCARs, supplier follow-up |
| Incoming Quality (IQC) inspector | Daily user, mobile | 30-second rejection capture |
| Purchase / Stores | Occasional | Receipts, debit notes, supplier status |
| Supplier quality contact (external) | Responds | 8D responses, documents — via WhatsApp/email link, no account |

**Internal roles (R1):** Admin, Quality User, Viewer. **Status changes and use-as-is dispositions** require a user flagged `can_approve` (Head of Quality).

---

## 3. The control loop

```text
Supplier → Part → Receipt (GRN / lot)
   ↓
Defect found → NCR (30 seconds, photo)
   ↓
Containment + disposition
   ↓
SCAR decision gate (severity, repeat, cost, customer impact)
   ↓
SCAR / 8D issued (one SCAR may cover several NCRs)
   ↓
Supplier responds through a secure link (WhatsApp / email)
   ↓
SQE reviews → accept / send back
   ↓
Financial exposure recorded → debit note → recovery
   ↓
Effectiveness verified (lots AND time window)
   ↓
Supplier Quality Score + risk recalculated
   ↓
Next action surfaced
```

Supplier documents and certificates run as a parallel, lower-frequency loop.

### 3.1 Four engines

| Engine | Contents |
| --- | --- |
| **Capture** | Suppliers, contacts, parts, receipts, NCRs, documents, certificates, imports |
| **Resolve** | Containment, disposition, SCAR, 8D, corrective action, effectiveness |
| **Measure** | PPM, rejection rates, repeat defects, supplier response, financial exposure, certificate compliance |
| **Decide** | Risk, escalation, watchlist, supplier status, management actions |

Every feature must strengthen one engine and the loop. If it does not, defer it.

---

## 4. Product principles

1. **The loop first.** Rejections, SCARs, exposure and effectiveness drive weekly use and ROI.
2. **Suppliers never need an account.** Every supplier action is a secure link plus OTP.
3. **30-second capture.** If an inspector cannot log a rejection in 30 seconds on a phone, it will not be logged. Measure it.
4. **Excel in, Excel out.** Every master list imports and exports. Live ERP integration comes later.
5. **Opinionated defaults.** One NCR form, one 8D format, one score formula. Configure only what customers truly differ on.
6. **Trustworthy numbers.** Every metric shows value, sample size, coverage and freshness. Insufficient data shows "N/A", never a perfect score.
7. **Every number drills down** to the records and the calculation behind it.
8. **Every risk explains itself** with structured reasons.
9. **AI assists, humans decide.** AI never approves, rejects, closes, changes status or calculates money.
10. **WhatsApp is a channel, not a dependency.** Every flow works over email and web link.
11. **Records are never silently changed.** State changes go through explicit commands, with audit trail and reasons.
12. **Speak plant language:** GRN, IQC, PPM, 8D, 4M, PDI, MTC, debit note.

---

## 5. Scope

### 5.1 R1 Core — build from day one

| # | Module | Engine |
| --- | --- | --- |
| C1 | Tenant, plants, users, roles | Platform |
| C2 | Suppliers, contacts (identity lifecycle), parts, supplier–part mapping | Capture |
| C3 | Import engine with batches, de-duplication and reconciliation | Capture |
| C4 | Receipts (GRN / lot) | Capture |
| C5 | NCR with 30-second capture, containment, disposition, cost lines | Capture / Resolve |
| C6 | SCAR decision gate, SCAR with many-to-many NCR links, severity policy | Resolve |
| C7 | Supplier response: magic link + OTP + scoped session, 8D form | Resolve |
| C8 | Effectiveness verification | Resolve |
| C9 | Financial exposure and debit notes | Measure |
| C10 | Documents and certificates with AI extraction and human review | Capture |
| C11 | Supplier Quality Score with coverage; risk engine with windows and reasons | Measure / Decide |
| C12 | "My Work" action queue, Supplier Quality Case page, Supplier 360, drill-down dashboard | Decide |
| C13 | Notifications (WhatsApp + email + in-app) via outbox, consent records | Platform |
| C14 | Monthly report PDF, supplier report card, Excel exports | Decide |
| C15 | Audit trail, explicit state machines, tenant-isolation tests | Platform |

### 5.2 R1.1 — after the first pilot

- Data-health screen (§19)
- Supplier response-behaviour metrics (§18)
- Target hierarchy beyond tenant default + supplier-part override (§14.4)
- Risk override governance UI (§15.5)
- Supplier Quality Evidence Pack export (§21.3)
- Certificate exceptions / waivers UI (§13)
- Plant holiday calendar for SLAs

### 5.3 Not in R1

Supplier login portal; qualification questionnaires; audit management; inspection plans, measurements, sampling, SPC, MSA; PPAP workflow (documents stored only); 4M change and deviation workflows; delivery performance; configurable workflow builder or custom fields; live ERP integrations; AI copilot and semantic search; SSO/SCIM; multi-region; native mobile and offline mode; microservices, Kafka, Kubernetes.

---

## 6. Data model

PostgreSQL. Every table has `id` (uuid), `tenant_id`, `created_at`, `created_by`, `updated_at`, `updated_by`. Row-level security on `tenant_id` from the first migration. Plant-scoped objects carry `plant_id`.

### 6.1 Platform

| Table | Key columns |
| --- | --- |
| `tenants` | name, plan, settings (json: SLA hours, default PPM target, minimum sample sizes, score weights) |
| `plants` | name, code, address, timezone |
| `users` | email, name, mobile, role (admin / quality / viewer), can_approve, plant_ids, active |
| `activity_log` | object_type, object_id, action, before (json), after (json), reason, actor_type (user / supplier_session / system / ai), actor_id, session_id, ip, created_at |
| `outbox_events` | event_id, aggregate_type, aggregate_id, event_type, payload (json), created_at, processed_at, attempts, last_error |

### 6.2 Masters

| Table | Key columns |
| --- | --- |
| `suppliers` | code, name, gstin, city, state, category, **status** (approved / approved_with_action_plan / on_watch / blocked / inactive), status_reason, status_changed_by, status_changed_at |
| `supplier_contacts` | supplier_id, name, role, mobile, email, is_quality_contact, verified_mobile_at, verified_email_at, active, disabled_at, disabled_reason, replaced_by_contact_id |
| `contact_consents` | contact_id, channel (whatsapp / email / sms), status (opted_in / opted_out), source, consent_at, revoked_at |
| `customers` | name (OEM), code |
| `parts` | part_no, name, category, current_revision (nullable text) |
| `customer_parts` | customer_id, part_id, customer_part_no — *many-to-many; no customer_id on parts* |
| `supplier_parts` | supplier_id, part_id, supplier_part_no, status, ppm_target (nullable override) |

### 6.3 Receipts and quality

| Table | Key columns |
| --- | --- |
| `grn_receipts` | plant_id, grn_no, grn_date, supplier_id, part_id, lot_no, part_revision, qty_received, source (import / manual), import_record_id — **unique** (tenant, plant, grn_no, part_id, lot_no) |
| `defect_codes` | code, name, defect_category (dimensional / material / surface-visual / functional / packaging-labelling / documentation / other), characteristic (optional, e.g. "bore diameter"), active — *tenant-level list, seeded with defaults, editable by Admin* |
| `defect_events` | **the single source of rejected physical quantity** — receipt_id (nullable until attributed), supplier_id, part_id, plant_id, qty_rejected, defect_code_id (nullable for unattributed ERP rows), defect_category, detected_at, source (ncr_capture / erp_import / manual), source_ref (import_record_id or ncr_id), ncr_id (nullable), attribution_status (attributed / unattributed / superseded), superseded_by_event_id, attributed_by, attributed_at |
| `ncrs` | ncr_no, plant_id, supplier_id, part_id, grn_id (nullable), lot_no, part_revision, detected_at, qty_checked, **qty_rejected (derived: Σ attributed defect_events of this NCR)**, primary_defect_code_id, defect_category, severity, description, status, is_repeat, customer_disruption (bool), disposition, disposition_by, disposition_at, capture_started_at, capture_submitted_at, cancelled_reason |
| `defect_event_attributions` | erp_event_id, ncr_event_id (nullable), decision (same_rejection / same_rejection_qty_corrected / different_defect / internal_not_supplier), erp_qty, ncr_qty, accepted_qty, difference_qty, reason, decided_by, decided_at — *permanent record of every attribution; never edited, only superseded by a new decision* |
| `ncr_photos` | ncr_id, file_key, taken_at |
| `ncr_containment` | ncr_id, action, qty, location (our plant / supplier / in-transit / customer), done_by, done_at |
| `ncr_costs` | **exposure lines** — ncr_id, cost_type (material / sorting / rework / scrap / line_stop / premium_freight / customer_penalty / inspection / lab_test / other), amount_inr, basis, incurred_on, recoverable (bool), entered_by |
| `scars` | scar_no, supplier_id, plant_id, severity, status, issued_at, containment_due_at, final_due_at, first_response_at (first supplier action of any kind), final_response_at (first **complete** D3–D7 submission; later revisions after send-back do not move it), accepted_at, closed_at, revision, waived_reason |
| `ncr_scar_links` | ncr_id, scar_id, relationship (primary / related), created_at |
| `scar_responses` | scar_id, revision, d3_containment, **occurrence_cause**, **escape_cause**, **systemic_cause**, cause_category (man / machine / material / method / measurement / environment), five_why (json), corrective_actions (json: action, owner, due, done), preventive_actions (json), submitted_at, submitted_by_contact_id |
| `scar_evidence` | scar_id, response_revision, file_key, description |
| `scar_reviews` | scar_id, revision, decision (accept / send_back), comment, reviewer_id, reviewed_at |
| `effectiveness_checks` | scar_id, supplier_id, part_id, **signature** (json: defect_code_ids, defect_category, characteristic), start_at, min_lots, min_days, min_qty, lots_seen, qty_seen, matched_defect_event_id (nullable), result (pending / passed / failed / closed_no_data), extensions (int), decided_at, decided_by, decision_reason |
| `debit_notes` | dn_no, dn_date, supplier_id, amount_inr, status (raised / accepted / partly_recovered / recovered / disputed / written_off) |
| `debit_note_allocations` | debit_note_id, ncr_cost_id, amount_inr — **may reference only cost lines with `recoverable = true`; Σ allocations = debit note amount; Σ allocations per cost line ≤ cost line amount** |
| `recoveries` | debit_note_id, amount_inr, recovered_on, method (supplier credit note / payment set-off / replacement material / other), reference, recorded_by |
| `recovery_allocations` | recovery_id, debit_note_allocation_id, amount_inr — *auto-allocated pro-rata to each allocation's **remaining outstanding** (allocation − recovered − written off), never above it; rounding remainder to the allocation with the largest outstanding; manual override allowed within the same limit* |
| `write_offs` | debit_note_allocation_id, amount_inr, reason, approved_by, written_off_on — **invariant: recovered + written_off ≤ allocation amount per allocation** |

### 6.4 Documents

| Table | Key columns |
| --- | --- |
| `documents` | supplier_id, doc_type, file_key, file_hash, status, uploaded_via (supplier_link / internal), version, supersedes_id |
| `certificates` | document_id, cert_type, cert_no, standard, issuer, holder_name, issue_date, expiry_date, scope, status (pending_review / approved / rejected / superseded), reviewed_by, reviewed_at — **validity is never stored; computed from `expiry_date` (§7.3)** |
| `document_requirements` | supplier_category, doc_type, mandatory, validity_note, grace_days (default 14) — *the template* |
| `supplier_requirements` | supplier_id, doc_type, status (not_requested / requested / pending_review / approved), requested_at, due_at (= requested_at + grace_days), current_certificate_id, renewal_requested_at, renewal_due_at — *one row per supplier per mandatory doc type; created when a supplier is created or its category changes* |
| `certificate_exceptions` | supplier_id, doc_type, reason, approved_by, valid_until — *R1.1 UI, table in R1* |
| `ai_extractions` | document_id, source_hash, model, model_version, prompt_version, extraction_version, fields (json: value, confidence, source_span), validation_results (json), latency_ms, cost, review_status, corrected_fields (json) |

### 6.5 Supplier access and messaging

| Table | Key columns |
| --- | --- |
| `magic_links` | token_hash, purpose (scar_response / document_upload), object_type, object_id, contact_id, expires_at, opened_at, revoked_at, revoked_reason |
| `supplier_sessions` | magic_link_id, contact_id, object_type, object_id, otp_verified_at, expires_at, revoked_at, ip, user_agent |
| `messages` | channel, template_code, language, recipient_contact_id / user_id, variables (json; state-change notifications include `state`, e.g. `expiring_30` or `overdue`), object_type, object_id, idempotency_key, provider_message_id, status (queued / sent / delivered / read / failed / expired), clicked_at, responded_at, error |
| `tasks` | type, object_type, object_id, assignee_id, due_at, status, priority |

### 6.6 Measurement and risk

| Table | Key columns |
| --- | --- |
| `supplier_scores_monthly` | supplier_id, plant_id, period_start, period_end, calculated_at, formula_version, ppm, qty_rejection_pct, lot_rejection_rate, lots_received, qty_received, quality_score, response_score, repeat_score, document_score, total_score, grade, coverage_pct, components_na (json) — **immutable** |
| `risk_events` | supplier_id, rule_code, points, params (json), source_object_type, source_object_id, window_start, window_end, active, first_seen_at, cleared_at |
| `supplier_risk_current` | supplier_id, system_score, system_level, reasons (json), calculated_at, trend (up / flat / down) |
| `risk_overrides` | supplier_id, system_level, override_level, reason, override_by, override_at, expires_at — *R1.1 UI, table in R1* |
| `quality_targets` | scope (tenant / supplier_part), scope_id, metric (ppm), target_value, effective_from, effective_to |

### 6.7 Imports

| Table | Key columns |
| --- | --- |
| `import_batches` | entity (suppliers / parts / supplier_parts / receipts / ncrs / certificates_meta), file_name, file_hash, mapping (json), status, rows_received, rows_valid, rows_imported, rows_duplicate, rows_rejected, rows_unmapped, rows_review, started_by, confirmed_at |
| `import_records` | batch_id, row_number, row_hash, source_record_id, status (imported / duplicate / rejected / unmapped / review), reason, target_id |

**Numbering:** `NCR-{plant}-{YYMM}-{seq}`, `SCAR-{YYMM}-{seq}`, `DN-{YYMM}-{seq}`.

---

## 7. State machines

All transitions go through **command endpoints** (§24.2), are authorised, write `activity_log`, and emit an outbox event. No generic "update status" endpoint.

### 7.1 NCR

```text
OPEN → CONTAINED → (AWAITING_SCAR | MONITOR | LOCAL_CLOSE)
AWAITING_SCAR → LINKED_TO_SCAR → VERIFICATION → CLOSED
MONITOR → CLOSED            (no SCAR required, reason recorded)
LOCAL_CLOSE → CLOSED        (minor, handled internally, reason recorded)
Any open state → CANCELLED  (reason required, Admin or can_approve)
```

### 7.2 SCAR

```text
DRAFT → ISSUED → RESPONSE_STARTED → RESPONSE_SUBMITTED → UNDER_REVIEW
UNDER_REVIEW → SENT_BACK → RESPONSE_STARTED (revision + 1)
UNDER_REVIEW → ACCEPTED → EFFECTIVENESS → CLOSED (passed, or closed_no_data with reason)
EFFECTIVENESS → REOPENED (effectiveness failed) → RESPONSE_STARTED
EFFECTIVENESS → EFFECTIVENESS (extended: new window, reason, extensions + 1)
DRAFT / ISSUED → CANCELLED (reason required)
```

### 7.3 Certificate

**Stored review status** (changed only by commands):

```text
PENDING_REVIEW → APPROVED / REJECTED
APPROVED → SUPERSEDED (a newer version of the same doc type is approved)
```

**Computed validity** (never stored, recalculated on every read from `expiry_date` and today's date in the plant timezone):

| Validity | Condition |
| --- | --- |
| valid | expiry > today + 60 days |
| expiring_60 | today + 30 < expiry ≤ today + 60 |
| expiring_30 | today + 7 < expiry ≤ today + 30 |
| expiring_7 | today ≤ expiry ≤ today + 7 |
| expired | expiry < today |

Only `APPROVED` certificates have a validity. Reminders, risk rules and compliance read the computed validity, so a failed background job can never leave a certificate in a stale state.

### 7.4 Supplier document requirement

```text
First-time (no current certificate):
NOT_REQUESTED → REQUESTED → PENDING_REVIEW → APPROVED
REQUESTED → (due_at passes, nothing uploaded) → still REQUESTED, now overdue
PENDING_REVIEW → REQUESTED (upload rejected; new due_at; requirement is missing until approved)

Renewal / replacement (a current certificate exists):
APPROVED stays APPROVED throughout.
  - When the current certificate reaches expiring_60 (or an SQE asks for a replacement),
    renewal_requested_at / renewal_due_at are set and the supplier is asked for the new copy.
  - The uploaded replacement is a certificate in PENDING_REVIEW; the requirement status does not change.
  - Replacement approved → it becomes current_certificate_id; the old one is SUPERSEDED.
  - Replacement rejected → current_certificate_id is unchanged; renewal_due_at is reset;
    the supplier is asked again. If the current certificate is still valid, the supplier
    remains compliant; if it has expired, the requirement is non-compliant (computed).
```

**What `status = approved` means.** It means the requirement has been satisfied at least once and has a `current_certificate_id`. It does **not** mean "currently compliant". Current compliance is always computed from `current_certificate_id` + that certificate's computed validity + any active exception. Never use `status = approved` alone as a compliance check.

**Exceptions are not a stored status.** A requirement is "under exception" when a row in `certificate_exceptions` has `valid_until ≥ today` — computed on read, like validity, so an exception can never be left stuck after it lapses.

### 7.5 Editing and retention rules

| Object | Rule |
| --- | --- |
| NCR, SCAR, debit note, certificate | Never hard-deleted. Cancel with reason. |
| Closed NCR / SCAR | Immutable; corrections via "reopen" command with reason |
| Debit amounts, dispositions, certificate approvals, supplier status | Editable only through commands; before/after + reason logged |
| Score snapshots | Immutable |
| Supplier responses | Every revision kept; never overwritten |
| Masters (supplier, part) | Archive (`archived_at`), never delete if referenced |

---

## 8. Module specs — Capture

### C2. Suppliers, contacts, parts

- **Supplier:** code, name, GSTIN (optional), city, state, category (raw material / bought-out / job work / service), status (§15.6).
- **Contacts lifecycle:** add, verify mobile (OTP), mark quality contact, disable (reason), replace (old contact's links and sessions are revoked automatically; open SCARs reassigned to the new contact).
- **Phone reassignment protection:** a contact unverified for 180 days is re-verified by OTP before receiving new links.
- **Parts:** part number, name, category, optional current revision; linked to customers via `customer_parts`; linked to suppliers via `supplier_parts`.
- **Supplier 360 page:** status and risk (shown separately), score with components and coverage, open NCRs/SCARs, exposure, certificates, contacts, timeline of all events and messages.

### C3. Import engine

```text
Upload → Detect columns → Map (saved per tenant) → Validate → Preview
→ Show errors / duplicates / unmapped → Confirm → Import → Reconciliation report
```

- File hash check: the same file uploaded twice is flagged before processing.
- Row hash + natural keys: suppliers (GSTIN, or name + city), parts (part_no), receipts (plant + GRN no + part + lot), ERP rejections (plant + GRN no + part + lot + ERP rejection reference or row hash).
- ERP rejection rows become **unattributed `defect_events`** (source `erp_import`) and go through attribution (§11).
- Duplicates are **reported, never silently merged**.
- Every batch produces a report: received / valid / imported / duplicate / rejected / unmapped / needs review — downloadable as Excel with a reason per row.
- Partial imports require explicit confirmation.

**Acceptance:** importing the same 5,000-row receipt file twice creates zero duplicate receipts and a report showing 5,000 duplicates.

### C4. Receipts (GRN / lot)

- Source: Excel/CSV upload (daily or weekly) or manual entry.
- Fields per §6.3. If the ERP export also contains rejections, they are imported as separate ERP rejection rows (→ `defect_events`), never as a column that is added to NCR quantities.
- Receipts are the **denominator** for every quality rate.

### C5. NCR — 30-second capture

**Mobile flow (target median ≤ 30 s, p90 ≤ 60 s):**

1. Photo(s)
2. Supplier → part (search, recent first; scanning the GRN number pre-fills both)
3. Qty checked
4. Defect(s): pick a defect code (recent codes for this part first; search; or pick only the category if unsure) and the rejected qty **per defect** — one NCR can hold several defects, each saved as a `defect_event`
5. Severity: minor / major / critical
6. Optional: GRN, lot, revision, description (voice-to-text, Hindi or English), **customer disruption** checkbox

`capture_started_at` and `capture_submitted_at` are stored to measure capture time.

**Defect signature:** supplier + part + defect code (falls back to defect category when no code was chosen). Used for repeat detection, SCAR grouping, effectiveness and risk.

**Repeat flag:** same defect signature within 90 days.

**If an unattributed ERP rejection exists for the same receipt,** the capture screen offers "This is the same rejection" (attributes the ERP event to this NCR) or "This is a different defect".

**Containment:** action list (quarantine, sort at our plant, sort at supplier, stop usage, inform customer), qty, location, who, when.

**Disposition:** return to supplier, rework at our end, sort and use, scrap, **use-as-is (requires can_approve)**.

**Cost lines (optional at capture, expected before closure):** see `ncr_costs` types.

**Acceptance:** an inspector on a mid-range Android phone logs an NCR with a photo in ≤ 30 s; it appears on the SQE's My Work instantly.

### C10. Documents and certificates

**Default types:** ISO 9001, IATF 16949, ISO 14001, ISO 45001, NABL accreditation, calibration certificate, material test certificate (MTC), RoHS/REACH declaration, quality agreement, PPAP documents (stored only), other.

**Requirements:** default mandatory list per supplier category, editable by Admin. When a supplier is created (or its category changes), one `supplier_requirements` row per mandatory doc type is created as `not_requested`. A bulk "Request all missing documents" action sends requests and sets `due_at`. Requirements still `not_requested` after 7 days appear on My Work.

**Request flow:** request → WhatsApp + email with link → OTP → upload → AI extraction → validation → SQE review → approve / reject (reason) → previous version superseded.

**Expiry escalation:**

| When | Action |
| --- | --- |
| 60 days before | Auto-request to supplier |
| 30 days before | Reminder to supplier + task for SQE |
| 7 days before | Reminder + escalation to Head of Quality |
| Expired (computed) | Risk rule fires, daily reminder to supplier for 7 days then weekly |
| Exception (R1.1 UI) | Head of Quality records a time-bound exception; risk rule suppressed until `valid_until` |

---

## 9. Module specs — Resolve

### C6. SCAR decision gate and severity policy

When an NCR is contained, the system recommends one of: **SCAR required / Monitor / Local close / Add to existing SCAR**. The SQE decides; the choice and reason are logged.

**Severity policy (defaults, tenant-configurable later):**

| Severity | SCAR | Containment due | Final 8D due | Notify | Effectiveness window |
| --- | --- | --- | --- | --- | --- |
| Critical | Mandatory | 24 h | 7 days | Head of Quality immediately | 5 lots AND 60 days |
| Major | Required unless waived with reason | 48 h | 10 days | SQE | 3 lots AND 30 days |
| Minor | Optional; required on 2nd repeat in 90 days | — | 15 days if issued | SQE digest | 3 lots AND 30 days |

**SLA clock:** R1 uses **calendar hours** in the plant's timezone. Plant holiday calendar is R1.1. Response times are computed only from the explicit timestamps on `scars` — never from `updated_at`.

**Grouping:** one SCAR can link many NCRs (`ncr_scar_links`); a new NCR with the same defect signature as an open SCAR is suggested for linking to it.

### C7. Supplier response — link, OTP, scoped session

**Access lifecycle:**

```text
Generate random 32-byte token → store hash only → send via WhatsApp + email
→ supplier opens link → OTP to the contact's verified mobile (or email)
→ create supplier session scoped to ONE object, valid 7 days
→ link valid 30 days to re-open with a new OTP
→ revoke on: contact disabled/replaced, SCAR closed/cancelled, manual revoke
```

**What the supplier sees:** SCAR number, part, defect description, photos, quantities, due dates, D3–D7 form, evidence upload, review comments addressed to them, message thread for this SCAR.

**What the supplier never sees:** internal risk, score, costs, debit amounts, internal comments, other NCRs/SCARs, other suppliers' data.

**8D form (mobile-first, saves drafts):**

- D1/D2 pre-filled from linked NCRs
- **D3 Containment** — action, quantity, location, date
- **D4 Root cause** — three required fields:
  - *Occurrence cause* — why the defect was produced
  - *Escape cause* — why it was not detected before dispatch
  - *Systemic cause* — which system or standard failed to prevent it
  - cause category (6M) and guided 5-Why
- **D5/D6 Corrective actions** — action, owner, due date, done, evidence
- **D7 Preventive actions** — what changes elsewhere (other parts, lines, documents)
- D8 closure is internal

**Reminders:** day before due, on due, every 2 days overdue; escalation to Head of Quality at 3 days overdue (critical: 1 day).

**Review:** Accept, or Send back with comment → new revision → new notification. All revisions retained.

**Acceptance:** a supplier with no account completes D3–D7 on a phone, including evidence uploads; revisions and every timestamp are stored.

### C8. Effectiveness verification

- Starts when a SCAR is accepted. The check stores the SCAR's **defect signature**: supplier + part + the defect codes (or categories) of its linked NCRs, plus characteristic where recorded.
- Criteria (per severity policy): **minimum lots AND minimum days**, plus optional minimum quantity.
- Watches new receipts for the same supplier + part and new `defect_events` on them.
- **Passed:** criteria met with no defect event matching the signature → SCAR and linked NCRs can close.
- **Failed:** an attributed defect event matching the signature → SCAR moves to REOPENED, the matching event is stored, supplier notified, `EFFECTIVENESS_FAIL` fires.
- **Different defect on the same part:** does not fail effectiveness; it creates its own NCR. The SQE is shown "Possible related defect" and may link it manually, with reason.
- **Unattributed ERP rejection on a watched receipt:** effectiveness is held (not passed) until the rejection is attributed.
- **Not enough receipts in window:** after 90 days pending, the check appears on My Work and the SQE must choose one command (reason required):
  - **Extend** — new window (lots/days), `extensions + 1`; after 2 extensions only Close is offered
  - **Close – no data** — SCAR closes with effectiveness `closed_no_data`; shown as "not verified" in reports and the Evidence Pack, and counted separately from passed
- Effectiveness is never passed or failed without data.

---

## 10. Module specs — Measure

### C9. Financial exposure and debit notes

**Money chain:**

```text
NCR cost lines (exposure)
   ↓ allocated by
Debit note allocations (Σ = debit note amount; ≤ each cost line)
   ↓ settled by
Recoveries → recovery allocations (pro-rata to remaining outstanding by default, manual override)
   or
Write-offs (per allocation, reason + approver)
```

Every rupee recovered or written off is traceable to a specific cost line, NCR, supplier and part.

**Per cost line:**

```text
debited     = Σ debit_note_allocations
recovered   = Σ recovery_allocations
written_off = Σ write_offs
undebited   = amount − debited          (only if recoverable = true)
outstanding = debited − recovered − written_off
net_exposure = amount − recovered
```

**KPIs — two views, never mixed:**

| View | Question | Definition |
| --- | --- | --- |
| **Exposure cohort** (default) | "Of the defects that happened in September, how much have we recovered so far?" | Cohort = cost lines with `incurred_on` in period. Gross exposure, debited, recovered (to date), written off, outstanding, net exposure and **Recovery % = recovered ÷ gross exposure** — all on that same cohort. |
| **Cash view** | "How much did we recover this month?" | Σ recoveries with `recovered_on` in period, broken down by the exposure month they relate to. No percentage is computed in this view. |

**Rules:**
- A debit note cannot be saved until its full amount is allocated to cost lines.
- Allocations may reference only cost lines with `recoverable = true`; non-recoverable costs (e.g. our own inspection) stay in exposure but can never be debited.
- Per allocation, always: **recovered + written_off ≤ allocation amount**. A recovery or write-off that would break this is rejected. Enforced in the application command and by a database constraint trigger.
- Therefore `outstanding` can never be negative.
- Changing an allocation after recovery requires a command with reason (§7.5).
- Amounts are entered by people; AI never calculates or edits money.

---

## 11. Rejected quantity — defect events and attribution

### 11.1 Principle

Every physically rejected unit is represented by **exactly one active `defect_event`**. Metrics sum defect events; they never add NCR quantities to ERP quantities, and never take a max of the two.

### 11.2 Sources

| Source | Creates | Initial status |
| --- | --- | --- |
| NCR capture (one event per defect on the NCR) | `defect_event` with defect code, linked to NCR and receipt | attributed |
| ERP rejection import | `defect_event` without defect code, linked to receipt | unattributed |
| Manual entry (rejection without NCR) | `defect_event` with defect code | attributed |

### 11.3 Attribution

An unattributed ERP event is resolved in one of four ways. Every decision writes a `defect_event_attributions` row (user, time, quantities, reason):

| Decision | Effect |
| --- | --- |
| **Same rejection as NCR X** (quantities match) | ERP event marked `superseded` by the NCR's event → counted once |
| **Same rejection, different quantity** | User confirms the correct quantity; the other event is superseded; ERP qty, NCR qty, accepted qty and difference are stored in `defect_event_attributions` with a reason |
| **Different defect** | ERP event gets a defect code (and optionally an NCR) → both count |
| **Not a supplier defect** (handling damage, our process) | ERP event marked `superseded` with reason "internal" → excluded from supplier metrics |

**Auto-suggestions:** when an ERP event and an NCR share receipt + equal quantity, the system proposes "same rejection"; the user confirms with one tap. The system never attributes on its own.

### 11.4 What counts in metrics

Two quantities are kept per receipt and never mixed:

```text
attributed_qty(receipt)   = Σ qty of active ATTRIBUTED events on the receipt
unattributed_qty(receipt) = Σ qty of active UNATTRIBUTED (ERP) events on the receipt

if attributed_qty > 0 and unattributed_qty > 0:      -- possible overlap
    canonical_rejected_qty = attributed_qty
    unreconciled_qty       = unattributed_qty          -- shown separately, NOT in PPM
else:                                                  -- no overlap possible
    canonical_rejected_qty = attributed_qty + unattributed_qty
    unreconciled_qty       = 0
```

- **PPM and all rejection rates use `canonical_rejected_qty` only.**
- When a supplier has any `unreconciled_qty` in the period, its PPM is labelled **"Provisional"** with the unreconciled quantity shown next to it ("1,240 PPM · provisional · 120 units unreconciled").
- Once attributed, the receipt is recalculated and the label disappears.
- Unattributed events carry no defect code, so they never count toward repeats, signatures or effectiveness.
- Defect events without a receipt (NCR not linked to a GRN) are suggested matches by supplier + part + lot; until matched they appear in "unlinked rejections" in data health and are excluded from PPM.

---

## 12. Metrics (exact definitions)

All metrics are per supplier (and per supplier-part where shown), per plant, for an explicit `period_start`–`period_end`.

| Metric | Formula |
| --- | --- |
| **PPM** | Σ canonical_rejected_qty ÷ Σ qty_received × 1,000,000 — receipts with `grn_date` in period (§11.4); marked provisional if unreconciled qty > 0 |
| **Quantity rejection %** | Σ canonical_rejected_qty ÷ Σ qty_received × 100 |
| **Lot rejection rate** | receipts with canonical_rejected_qty > 0 ÷ receipts × 100 |
| **Unreconciled rejected qty** | Σ unreconciled_qty in period — shown beside PPM, never added to it. It is a **conservative unresolved quantity**, not a count of physically distinct units: ERP 100 + NCR 60 on one receipt shows 100 unreconciled even though up to 60 may be the same units. The UI labels it "awaiting reconciliation", never "extra rejected units". |
| **PPM by defect** | same as PPM, restricted to attributed events with a given defect code/category (Pareto) |
| **Repeat NCRs** | NCRs flagged `is_repeat` (same defect signature within 90 days) in period |
| **Customer disruptions** | NCRs with `customer_disruption = true` in period |
| **Premium freight occurrences** | NCR cost lines of type `premium_freight` in period |
| **SCAR on-time %** | on_time ÷ (on_time + late + overdue) × 100, over all SCARs with `final_due_at` in period. Each such SCAR has exactly one computed due-status: **on_time** (first complete submission — `final_response_at` — ≤ final_due_at; quality of the response is measured separately by revisions and time to acceptance), **late** (final response after final_due_at), **overdue** (no final response and now > final_due_at). SCARs not yet due are excluded; open overdue SCARs always stay in the denominator. Cancelled SCARs are excluded. **Due-status is evaluated as of the period end** (see §14.5): a SCAR due in September and still open on 30 September is `overdue` in September's figures permanently, even if submitted on 5 October. |
| **Late completions** | SCARs whose `final_response_at` falls in the period but after their `final_due_at` in an earlier period — reported in the later month, never changing the earlier one |
| **Time to first response** | median(first_response_at − issued_at) |
| **Time to acceptance** | median(accepted_at − issued_at) |
| **Document compliance %** | compliant ÷ due × 100. **Compliant** = approved requirement whose current certificate's validity is not `expired`, or any requirement under an active exception. **Due** = all approved requirements (any validity), all under exception, and requested requirements whose `due_at` has passed. Requirements `not_requested`, or requested and not yet due, are excluded and shown as "pending". |
| **Recovery %** | Exposure-cohort definition in §10 |
| **NCR capture time** | median and p90 of (capture_submitted_at − capture_started_at) |

### 12.1 Every metric carries trust signals

| Signal | Meaning |
| --- | --- |
| **Sample** | lots and units (or SCAR count) behind the value |
| **Coverage** | share of receipts with mapped supplier/part; share of rejected qty linked to receipts; share of rejected qty attributed to a defect code |
| **Freshness** | time since last import / calculation |

**Minimum sample (defaults):** PPM and rejection metrics need ≥ 5 receipts **and** ≥ 1,000 units in the period; SCAR metrics need ≥ 1 SCAR due. Below the minimum, the value shows **"N/A — insufficient data"**.

---

## 13. Certificate exceptions (table R1, UI R1.1)

- A certificate can be expired or missing while supply is still operationally allowed — e.g. renewal audit done, new certificate awaited.
- A user with `can_approve` records an exception: supplier, document type, reason, `valid_until` (maximum 90 days).
- While active: document compliance counts the item as covered, `CERT_EXPIRED` / `CERT_MISSING` do not fire, and the supplier still receives reminders.
- On `valid_until`, the exception lapses automatically and normal rules resume.
- All exceptions appear in the Monthly Report and the Evidence Pack.

---

## 14. Supplier Quality Score

The score covers **quality**, not overall supplier performance. Delivery performance is R2.

### 14.1 Components and default weights

| Component | Weight | Scoring (0–100) |
| --- | --- | --- |
| Quality (PPM vs target) | 50% | 100 if PPM ≤ target; linear to 0 at 10× target |
| Responsiveness (SCAR on-time %) | 20% | = SCAR on-time % |
| Repeat / Disruption Signal | 15% | 100 − 25 per repeat NCR − 40 per customer disruption (min 0). *An intentionally opinionated composite signal, not a standardised quality metric; the underlying counts are always shown separately.* |
| Document compliance | 15% | = document compliance % |

### 14.2 Missing data

- A component below its minimum sample is **N/A**, not 100.
- The total is re-weighted across available components.
- If Quality is N/A, **no total score or grade is shown** — only "Insufficient data", with the available components listed.

### 14.3 Display

Always show the score with its components and coverage, never a grade alone:

```text
Grade B · 72
Quality 81 · Response 68 · Repeat 52 · Documents 91
Based on 42 lots / 82,000 units · Coverage 88% · Updated 2 h ago
```

**Grades:** A ≥ 85, B 70–84, C 50–69, D < 50.
**Ranking:** suppliers with insufficient data are listed separately, never ranked above measured suppliers.

### 14.4 Targets

R1: tenant default PPM target (set during onboarding from the customer's own policy; demo default 500) with optional override per supplier-part (`supplier_parts.ppm_target`). Fuller hierarchy (customer-part, commodity) is R1.1 using `quality_targets`.

### 14.5 Snapshots

On the 1st of each month, last month's score is written to `supplier_scores_monthly` with `formula_version`, period and inputs. Snapshots are immutable; changing weights or targets affects future periods only.

**As-of rule for every period metric:** a closed period is calculated **as of its period end**, using only event timestamps (`issued_at`, `final_response_at`, `accepted_at`, `recovered_on`, `decided_at`, etc.) that are on or before `period_end`. Events that happen later — a late 8D, an attribution decision, a recovery — appear in the period in which they happen and never rewrite an earlier snapshot. The live dashboard for the current period recalculates continuously; only closed periods are frozen.

Corrections to historical *data* (e.g. a wrong quantity fixed in March for a January receipt) do not change January's snapshot. They are listed in the next report as "Corrections to earlier periods", with the before/after values from the activity log.

---

## 15. Risk engine

### 15.1 Model

Risk is **recalculated from active conditions** nightly and on relevant events. It is not a running total: when a condition ends or ages out of its window, its points stop counting.

### 15.2 Rules

| Rule code | Condition (window) | Points | Params stored |
| --- | --- | --- | --- |
| `CRITICAL_NCR` | Critical NCR, last 30 days | +25 each (max 35) | ncr_id, date |
| `PPM_HIGH` | PPM > 3× target, current or last full month (min sample met) | +20 | ppm, target, period |
| `PPM_RISING` | Month PPM > 1.5× 3-month average (min sample met) | +10 | ppm, avg, change_pct |
| `SCAR_OVERDUE` | SCAR currently overdue | +10 each (max 30) | scar_id, days_overdue |
| `REPEAT_DEFECT` | Same defect signature ≥ 2 times, last 90 days | +15 | part, defect_code, count |
| `CUSTOMER_DISRUPTION` | NCR with customer disruption, last 90 days | +20 | ncr_id |
| `EFFECTIVENESS_FAIL` | Failed effectiveness (signature match), last 90 days | +15 | scar_id, defect_event_id, date |
| `CERT_EXPIRED` | Mandatory certificate expired, no active exception | +20 | doc_type, expiry |
| `CERT_MISSING` | Requirement `requested` and `due_at` (request + grace, default 14 days) has passed with no approved certificate | +10 | doc_type, requested_at, due_at |
| `CERT_EXPIRING` | Computed validity `expiring_30` or `expiring_7` | +5 | doc_type, expiry |
| `SUPPLIER_NO_RESPONSE` | Open request with no supplier action for ≥ 7 days | +10 | object, days |

Total capped at 100. **Levels:** Low 0–29, Medium 30–59, High ≥ 60.

### 15.3 Storage

Each active condition is a `risk_events` row with `rule_code`, `params`, window and source; when it clears, `active = false` and `cleared_at` is set. `supplier_risk_current` holds the score, level, reasons and trend. Reason text is generated from `rule_code` + `params`, so explanations are reproducible.

### 15.4 Display

```text
Risk HIGH · 70 · rising
• SCAR-2611-014 overdue 6 days
• Repeat dimensional defect on BRK-2201 (3 in 90 days)
• IATF 16949 certificate expired 12 Oct
```

### 15.5 Overrides (table R1, UI R1.1)

A user with `can_approve` may override the displayed level with a reason and expiry. The system score keeps calculating underneath; both are shown.

### 15.6 Risk and status are separate

| Concept | Meaning | Who sets it |
| --- | --- | --- |
| **Risk** | Analytical signal | System |
| **Status** | Management decision: approved, approved with action plan, on watch, blocked, inactive | Head of Quality (`can_approve`), with reason |

The system may **suggest** "on watch" after two consecutive months at High risk. It never changes status by itself.

---

## 16. Module specs — Decide

### C12. My Work, cases, dashboard

**First screen — My Work:**

```text
7 SCARs overdue                  (oldest first)
3 supplier responses to review
2 critical NCRs without containment
5 NCRs awaiting SCAR decision
6 ERP rejections to attribute
4 certificates expiring ≤ 30 days
₹4.2L net exposure this month
3 suppliers turned High risk
```

Each line opens its list; each item shows **what, why, owner, due, next action**.

**Supplier Quality Case page** (the main working screen): one SCAR with its linked NCRs, photos, containment, 8D revisions, review history, cost lines, debit notes, effectiveness status, supplier messages and the full activity history.

**Dashboard panels (below My Work):** worst suppliers by PPM (measured suppliers only), open/overdue SCAR ageing, exposure vs recovery, certificate status, repeat defects.

**Drill-down:** every number opens the records and a "How this was calculated" panel (formula, period, receipts, NCRs, exclusions, coverage).

### C14. Reports

- **Monthly Supplier Quality Report (PDF):** plant PPM and lot rejection trend, top suppliers by PPM (measured only), customer disruptions, NCR/SCAR status and ageing, time to response, exposure and recovery, certificate compliance, High-risk suppliers with reasons, top recurring defects, actions. Every metric shows its period and sample.
- **Supplier report card (PDF):** one page per supplier for monthly supplier reviews — no internal cost or risk detail unless the user chooses to include it.
- Excel export from every list (permission-checked, logged).

---

## 17. Notifications

### 17.1 Channels

WhatsApp (primary for suppliers) → email (always sent as record) → in-app → SMS (optional fallback). Every supplier flow works with email + web link alone.

### 17.2 Template abstraction

Application code raises a `notification_type`; the notification service chooses channel, template, language and variables. No WhatsApp logic outside `notifications/`.

| Type | Recipient |
| --- | --- |
| `SCAR_ISSUED` | Supplier contact |
| `SCAR_REMINDER` | Supplier contact |
| `SCAR_OVERDUE` | Supplier contact + SQE |
| `SCAR_SENT_BACK` | Supplier contact |
| `SCAR_ACCEPTED` | Supplier contact |
| `EFFECTIVENESS_FAILED` | Supplier contact + SQE |
| `DOC_REQUEST` | Supplier contact |
| `DOC_EXPIRY` | Supplier contact |
| `OTP` | Supplier contact |
| `ESCALATION` | Head of Quality |
| `DAILY_DIGEST` | SQE |

Templates in English and Hindi. WhatsApp business-initiated messages use pre-approved templates; free-form replies only within the 24-hour customer-service window.

### 17.3 Consent

Opt-in recorded per contact and channel (`contact_consents`). "STOP" / "UNSUBSCRIBE" replies set opted-out and switch that contact to email. Opt-out never blocks a workflow — it changes the channel.

### 17.4 Delivery tracking

Every message stores status transitions (queued → sent → delivered → read → failed/expired), link click and response time. Failed WhatsApp delivery triggers email/SMS fallback within 15 minutes.

---

## 18. Supplier response metrics (R1.1)

Per supplier and contact: time to first response, time to accepted 8D, on-time %, average revisions, evidence rejection %, form drop-off %, reminders sent, responses without internal follow-up. Shown on Supplier 360 and in pilot reviews.

---

## 19. Data health (R1.1)

One screen per plant:

```text
Supplier mapping        94%
Part mapping            89%
Receipt coverage        87%   (months with receipt data)
NCR → receipt linkage   92%
Rejected qty attributed 96%   (14 ERP rejections pending)
Unreconciled qty        120 units on 3 receipts (PPM provisional)
Requirements never requested  9
Attribution corrections 11 receipts (quantity differed ERP vs NCR)
Debit notes unallocated 0     (must always be 0)
Certificate coverage    76%
Last receipt import     3 h ago
```

Each line opens the records that need fixing.

---

## 20. AI layer

### 20.1 Policy

```text
AI = assistive · Core workflow = deterministic · Human = final authority
```

AI never: approves or rejects certificates, closes NCRs/SCARs, changes supplier status, overrides risk, calculates or edits money, or deletes records. If AI is unavailable, every workflow works manually.

### 20.2 Document extraction

```text
Upload (PDF/JPG/PNG ≤ 20 MB) → content-type check + virus scan
→ text layer or OCR → classify type → structured extraction (strict JSON schema)
→ validation rules → per-field confidence → human review → certificate record
```

**Validation rules:** expiry after issue; holder name fuzzy-matches supplier; type matches request; expiry not already past (flag); certificate number format plausible.

**Reproducibility:** store model, model version, prompt version, extraction version, source file hash, field source spans, reviewer and corrections (`ai_extractions`).

### 20.3 8D review assist

Checks and flags (suggestions only, shown to the SQE):

- Is each cause specific (not "operator error", "negligence", "human mistake" without a system fix)?
- Are occurrence and escape causes both answered and different?
- Does each corrective action address a stated cause?
- Is a systemic / preventive action present and not a copy of the corrective action?
- Is evidence attached for each completed action?
- Can effectiveness be verified objectively from receipts?

Plus a 3-line summary of the response.

### 20.4 NCR helpers

Voice-to-text (Hindi/English); defect-category suggestion from description and photo.

### 20.5 Benchmarks (run on every model or prompt change)

| Set | Size | Measures | Release gate |
| --- | --- | --- | --- |
| Certificates | 200 labelled | type, cert no, issuer, holder, issue date, expiry, scope accuracy; false-extraction rate | Type ≥ 95%, expiry ≥ 92%, cert no ≥ 90%; no metric drops > 2 points |
| 8D responses | 50 labelled | cause specificity, occurrence/escape distinction, action–cause link, systemic action, evidence completeness | Flag precision and recall tracked; no drop > 5 points |

Production: track correction rate per field weekly.

---

## 21. Security and data protection

### 21.1 Controls (R1)

TLS; encryption at rest; Postgres RLS + application authorisation; argon2/bcrypt passwords; login rate limits; secure sessions; private buckets; signed file URLs (≤ 15 min); content-type and size validation; virus scanning; audit logging of sensitive actions with before/after, reason, session and IP; daily encrypted backups.

### 21.2 Mandatory security tests (CI)

- Tenant A cannot read or write Tenant B suppliers, NCRs, SCARs, files
- Supplier session cannot access any object other than its own
- Supplier session cannot see internal costs, risk, comments
- Expired, revoked and used-up links fail
- Disabled contact's sessions fail
- Signed file URLs expire
- Viewer cannot export or download where not permitted

### 21.3 Supplier Quality Evidence Pack (R1.1)

One-click export per supplier: current score and history, risk with reasons, certificates, NCRs, SCARs with 8D revisions, effectiveness results, exposure and debit notes, messages and status history — for supplier reviews, management reviews and audit preparation. It supports evidence gathering; it is not a compliance guarantee.

### 21.4 Backup and recovery

RPO 24 hours, RTO 8 hours (R1 targets). Quarterly restore test with measured restore time.

### 21.5 Personal data (DPDP Act 2023)

Supplier contacts' names, mobiles and emails are personal data and appear in masters, messages, sessions, activity logs and uploaded documents. R1: privacy notice, recorded consent per channel, purpose limitation, contact deactivation, and an anonymisation routine for contacts on request (retaining quality records with the contact replaced by a placeholder). Retention periods and legal exceptions need legal review before making compliance claims.

### 21.6 Later (security roadmap)

DPA template, subprocessor register, security questionnaire pack, penetration test, incident-response runbook, access reviews, key rotation, SOC 2 / ISO 27001 readiness.

---

## 22. Architecture

**Modular monolith + background workers.**

| Layer | Choice |
| --- | --- |
| Frontend | Next.js, TypeScript, Tailwind; responsive + PWA for inspectors and suppliers |
| Backend | FastAPI, SQLAlchemy, Pydantic |
| Database | Managed PostgreSQL with RLS |
| Jobs | Redis + worker queue (extraction, notifications, imports, outbox dispatch, nightly risk, monthly snapshots, PDFs) |
| Files | S3-compatible storage in an Indian region; signed URLs only |
| AI | LLM with JSON-schema output + OCR, behind one provider interface |
| Messaging | WhatsApp Business Platform (BSP or Cloud API), email provider, optional SMS |
| PDF | HTML → PDF |
| Hosting | Single Indian region |
| Observability | Error tracking, structured logs, uptime checks, queue dashboard |

### 22.1 Backend layout

```text
app/
 ├── core/          # config, db, auth, tenancy, permissions, audit, outbox
 ├── masters/       # suppliers, contacts, parts, customers
 ├── imports/
 ├── receipts/
 ├── ncr/
 ├── scar/          # decision gate, links, responses, reviews
 ├── effectiveness/
 ├── finance/       # cost lines, debit notes
 ├── documents/     # documents, certificates, requirements, exceptions
 ├── supplier_access/  # magic links, OTP, supplier sessions
 ├── scoring/       # metrics, scores, snapshots, targets
 ├── risk/
 ├── notifications/ # channels, templates, consent, delivery tracking
 ├── ai/            # providers, extraction, 8D review, benchmarks
 ├── reports/
 └── api/
```

### 22.2 Reliability

- **Transactional outbox:** business change and `outbox_events` row are written in the same transaction; workers dispatch notifications, risk recalculation and reports from the outbox.
- **Idempotency:** external sends carry an `idempotency_key`; imports use file and row hashes; debit note creation uses a request ID.
- **Retries:** exponential backoff for WhatsApp, email, AI, PDF; dead-letter after 5 attempts with an alert.

### 22.3 Events

`NCR_CREATED`, `NCR_CONTAINED`, `SCAR_ISSUED`, `SCAR_RESPONSE_RECEIVED`, `SCAR_SENT_BACK`, `SCAR_ACCEPTED`, `SCAR_OVERDUE`, `EFFECTIVENESS_PASSED`, `EFFECTIVENESS_FAILED`, `EFFECTIVENESS_EXTENDED`, `EFFECTIVENESS_CLOSED_NO_DATA`, `DEFECT_EVENT_ATTRIBUTED`, `DEBIT_CREATED`, `DEBIT_RECOVERED`, `DEBIT_WRITTEN_OFF`, `CERTIFICATE_VALIDITY_CHANGED`, `REQUIREMENT_OVERDUE`, `RISK_CHANGED`, `SUPPLIER_STATUS_CHANGED`.

`CERTIFICATE_VALIDITY_CHANGED` and `REQUIREMENT_OVERDUE` are emitted by a daily scan that compares the current computed state with the **most recent successfully sent notification state for that object**: the latest `messages` row for the same object and notification type with status `sent`, `delivered` or `read`, whose `variables.state` holds the validity bucket or overdue flag it announced. If the computed state differs (or no such message exists), the event is emitted. A missed scan only delays notification; it never changes authoritative certificate or requirement data.

### 22.4 Monitoring

Technical: API and DB latency, queue depth, worker failures, outbox lag, WhatsApp/email failures, extraction failures, import failures, PDF failures.
Product: NCR capture time, supplier link open → submit conversion, SCAR response time, certificate processing time.

---

## 23. Onboarding

**Promise:** your first supplier-quality dashboard from your own data within 48 hours.

1. Customer shares: supplier list, part list, supplier–part mapping, last 3 months of receipts and rejections, folder of supplier certificates.
2. Import with reconciliation reports; resolve duplicates and unmapped rows with the customer.
3. AI processes certificates; low-confidence fields reviewed.
4. First dashboard and Monthly Report from their history in the kickoff meeting.
5. Production rollout (typically 1–3 weeks): supplier contact verification, WhatsApp opt-ins, user setup, severity policy confirmation, training for SQEs and inspectors.

---

## 24. Engineering conventions

### 24.1 Rules

1. Every table has `tenant_id`; RLS from the first migration.
2. Every state change through a command, with activity log and outbox event.
3. AI calls only from background jobs, through `ai/providers/`.
4. Every formula in §10–§15 has unit tests with fixed fixtures, including: insufficient data; ERP + NCR for the same rejection (counted once); ERP + NCR for different defects (both counted); internal (non-supplier) rejection excluded; one debit note across three NCRs with partial recovery and a write-off; recovery recorded in a later month than the exposure (cohort vs cash view); effectiveness with an unrelated defect on the same part (must not fail) and with a matching defect (must fail); allocation to a non-recoverable cost line (rejected); recovery + write-off exceeding an allocation (rejected); certificate validity changing across 60/30/7/0-day boundaries with no job run; new supplier with requirements not yet requested (no `CERT_MISSING`); requirement past due (fires); receipt with both NCR and unattributed ERP events (ERP qty excluded from PPM, PPM provisional); SCAR on-time with on-time, late, overdue and not-yet-due SCARs; a SCAR overdue at September month-end then submitted in October (September snapshot unchanged, October shows a late completion); rejected renewal upload while the current certificate is valid (still compliant, current_certificate_id unchanged); rejected first-time upload (requirement missing after new due date); daily scan run twice in a row (no duplicate notification) and skipped for a day (notification sent next run); effectiveness extend twice then close-no-data.
5. Supplier pages: no login, mobile-first, usable on a low-end Android phone over a slow connection.
6. Seed data: demo tenant with 50 suppliers, 120 parts, 3 months of receipts, 40 NCRs, 15 SCARs (some multi-NCR, some overdue, one reopened), 60 certificates — so every demo starts full.
7. Ask before adding any dependency that needs its own server.

### 24.2 Command endpoints (examples)

```text
POST /ncrs                                  POST /scars/{id}/issue
POST /ncrs/{id}/contain                     POST /scars/{id}/add-ncr
POST /ncrs/{id}/decide-scar                 POST /scars/{id}/accept
POST /ncrs/{id}/dispose                     POST /scars/{id}/send-back
POST /ncrs/{id}/cancel                      POST /scars/{id}/cancel
POST /ncrs/{id}/reopen                      POST /effectiveness/{id}/extend
POST /defect-events/{id}/attribute         POST /effectiveness/{id}/close-no-data
POST /suppliers/{id}/request-documents     POST /write-offs
POST /suppliers/{id}/change-status          POST /certificates/{id}/approve
POST /contacts/{id}/disable                 POST /certificates/{id}/reject
POST /contacts/{id}/replace                 POST /debit-notes/{id}/record-recovery
POST /supplier-access/{token}/verify-otp    POST /imports/{batch}/confirm
```

---

## 25. Pilot design

**Terms:** 60 days free; price agreed in writing upfront; converts unless cancelled.

**Measure weekly per plant:**

| Area | Measure | Healthy |
| --- | --- | --- |
| Capture | Rejections in system vs paper register | ≥ 80% |
| Capture | NCR capture time | median ≤ 30 s |
| Resolve | SCARs issued in system | ≥ 5 / month |
| Resolve | **Supplier responses without founder intervention** | ≥ 60% |
| Resolve | Time to first supplier response | trending down |
| Measure | Exposure and recovery recorded | ≥ 1 debit note / month |
| Decide | Weekly active internal users | ≥ 3 |
| Outcome | Overdue SCAR %, repeat NCR rate, PPM trend | improving or stable |
| Outcome | Time to retrieve supplier evidence | minutes, not hours |

**Go / kill at month 4:** go if at least 2 of 5 pilot plants pay **and** show independent weekly use, supplier responses without founder intervention, and willingness to be a reference. A plant that pays only because the founder operates the system is not validation.

---

## 26. Go-to-market

### 26.1 Positioning

**Supplier Quality Control for Indian Manufacturing** — capture every supplier rejection, chase every corrective action, track financial exposure, and know which suppliers are getting worse, without forcing suppliers to learn another portal.

### 26.2 Competition

| Type | Examples | Our angle |
| --- | --- | --- |
| Indian quality / manufacturing software | FastTQM, Nexgensis QMS, ERPDrive (depth of supplier-quality features to be verified) | Narrow and fast: supplier-quality loop only, suppliers without logins, exposure view, live with your data in days |
| Global supplier-quality platforms | 1factory, Supplios, ETQ, MasterControl, ComplianceQuest | India pricing, WhatsApp-first suppliers, India hosting |
| ERP quality modules | SAP QM, ERP add-ons | No ERP replacement; imports from ERP; usable by suppliers |
| Excel + WhatsApp + email + one experienced SQE | Everyone today | Same channels, but tracked, measured and preserved as evidence |

Sales question to answer in every deal: **"Why not extend our ERP?"** Answer with measurable outcomes from pilots — capture rate, supplier response time, overdue SCARs, exposure recovered.

### 26.3 Demo flow

Start with a story, not a dashboard:

```text
"Supplier ABC sent a bad lot."
Receipt → NCR in 30 s with photo → containment → SCAR decision
→ WhatsApp to supplier → supplier submits 8D on phone
→ SQE sends back weak root cause → supplier revises → accepted
→ exposure + debit note → effectiveness watching next lots
→ risk changes with reasons → monthly score with coverage
```

Lead-generation hook: **free supplier certificate compliance report** from 30 of the prospect's certificates within 24 hours.

### 26.4 Pricing (hypotheses to validate)

| Plan | Active suppliers | ₹/month per plant (ex-GST) |
| --- | --- | --- |
| Starter | ≤ 100 | 15,000 |
| Growth | ≤ 300 | 30,000 |
| Plant | ≤ 750 | 50,000 |
| Additional plant | — | 60% of plan |

Onboarding ₹50,000–1,00,000. Annual prepay: 2 months free. Fair-use WhatsApp included. All plans include every R1 module. Validate willingness to pay against hours saved, supplier response improvement, audit-preparation time, recovery value and repeat-defect reduction; keep pricing simple during pilots.

---

## 27. Build plan (12–16 weeks)

| Weeks | Build | Show design partners |
| --- | --- | --- |
| 1–2 | C1, C2, C3, C15 foundations: tenancy, RLS, roles, masters, import engine with reconciliation, audit log, outbox | Their supplier and part lists imported with a clean report |
| 3–4 | C10: documents, AI extraction, review, expiry tracking; certificate compliance PDF | Free compliance report on their certificates (sales hook) |
| 5–6 | C4, C5: receipts import, 30-second NCR, containment, disposition, cost lines | Last month's rejections captured; capture time measured |
| 7–8 | C6, C7, C13: decision gate, SCAR with multi-NCR links, magic link + OTP + sessions, 8D form, WhatsApp/email via outbox | A real supplier answering a real SCAR |
| 9–10 | C7 review loop, C8 effectiveness, C9 exposure and debit notes | Send-back and revision; exposure vs recovery |
| 11–12 | C11: metrics with coverage, score, snapshots, risk engine | Supplier ranking with reasons and sample sizes |
| 13–14 | C12, C14: My Work, Supplier Quality Case page, drill-downs, Supplier 360, reports | Monthly Supplier Quality Report from their data |
| 15–16 | Security tests, restore test, AI benchmarks, import hardening, billing, partner fixes | Convert pilots to paid |

R1.1 items (§5.2) start after the first pilot plant is live.

---

# PART B — ROADMAP

## 28. R2 (after ~5 paying plants)

### 28.1 PPAP (first priority for auto)

Start narrow: PPAP package per supplier-part and revision; submission level 1–5 (default 3); the 18 AIAG elements (design records, engineering change documents, customer engineering approval, DFMEA, process flow diagram, PFMEA, control plan, MSA studies, dimensional results, material/performance test results, initial process studies, qualified laboratory documentation, appearance approval report, sample parts, master sample, checking aids, customer-specific requirements, Part Submission Warrant); element-by-element review; PSW status (approved / interim / rejected); customer response. Supplier uploads via secure link. Do not expand into a full APQP suite without demand.

### 28.2 4M change / PCN

Supplier or SQE logs a change (Man, Machine, Material, Method) linked to supplier, part, revision; impact decision (none / trial lot / PPAP resubmission / audit); approval; effective date; trial-lot results; risk link.

### 28.3 Deviation / concession

Supplier request to ship off-spec: part, characteristic, deviation, quantity, validity, reason; internal (and customer) approval; affected receipts tagged.

### 28.4 Supplier performance (beyond quality)

Delivery schedule performance and premium-freight analysis from ERP data; customer disruption analysis; broader **Supplier Performance Score** alongside the Supplier Quality Score.

### 28.5 OEM complaint cascade and customer requirements

Customer complaint → linked parts and suppliers → supplier NCRs/SCARs; structured customer-specific requirements per customer, part and supplier.

### 28.6 Data model extensions

Supplier sites (quality by site); part revisions with effective dates and drawing/spec revisions; customer programs; target hierarchy (customer-part, commodity).

### 28.7 Other R2

Incoming inspection plans (characteristic, tolerance, sample, result → automatic NCR); light supplier audits (template, findings → SCAR); Tally / SAP Business One scheduled imports and debit-note export; offline NCR capture; similar-past-NCR retrieval; configurable score weights and SLA by customer.

## 29. R3 / enterprise

Supplier onboarding and qualification questionnaires; full requirement rules engine; full audit management; AQL sampling, SPC, MSA; configurable workflows and custom fields; full cost of poor quality; supplier development programs and review packs; lot traceability to finished goods; AI copilot with cited answers; anomaly detection and risk prediction; peer benchmarking (with sample size and segment always shown); SSO/SAML/SCIM; multi-company consolidation; multi-region; optional supplier portal for large suppliers; regulated-industry editions (21 CFR Part 11 e-signatures, computer system validation) as a separate product decision.

## 30. Advantage strategy

| Phase | Win on |
| --- | --- |
| 1 | Ease, speed, supplier response |
| 2 | Workflow history, data lineage, supplier behaviour history |
| 3 | Supplier intelligence, benchmarking, risk prediction |
| 4 (possible) | Shared supplier identity and evidence across customers, with consent and strict data governance |

WhatsApp, AI and dashboards are not advantages on their own. The durable asset is the connected history: supplier → part → receipt → defect → NCR → SCAR → causes → actions → effectiveness → cost → score → risk. Supplier reuse across customers is achievable early; a true network effect requires scale and is not assumed.

## 31. Feature decision test

Before adding anything, ask:

1. Does it improve Capture, Resolve, Measure or Decide?
2. Does it reduce manual work, supplier friction, response time or financial leakage?
3. Does it create reliable data?
4. Can the customer see its ROI?
5. Does it strengthen the supplier-quality loop?

If not, defer it.

---

## Appendix — Glossary

| Term | Meaning |
| --- | --- |
| GRN | Goods Receipt Note — record of material received |
| IQC | Incoming Quality Control |
| NCR | Non-Conformance Report — record of a defect / rejection |
| SCAR | Supplier Corrective Action Request |
| 8D | Eight-discipline problem-solving format |
| Defect event | One record of physically rejected quantity for one defect on one receipt; the single source for rejected qty |
| Defect signature | Supplier + part + defect code (or category); identifies "the same problem" |
| Attribution | Deciding whether an ERP rejection is the same as an NCR's rejection, a different defect, or not a supplier defect |
| Exposure cohort | All cost lines incurred in a period, tracked to their recovery over time |
| Occurrence cause | Why the defect was produced |
| Escape cause | Why the defect was not detected before dispatch |
| Systemic cause | Which system or standard failed to prevent it |
| CAPA | Corrective and Preventive Action |
| PPM | Parts per million rejected |
| Lot rejection rate | Share of received lots with any rejection |
| PDI | Pre-Dispatch Inspection report |
| MTC | Material Test Certificate |
| 4M / 6M | Man, Machine, Material, Method (+ Measurement, Environment) |
| PPAP / PSW | Production Part Approval Process / Part Submission Warrant |
| Debit note | Document charging the supplier for rejected material or costs |
| Exposure | Total cost caused by supplier defects, before recovery |
| IATF 16949 | Automotive quality management standard; clause 8.4 covers control of external providers |
| SQE | Supplier Quality Engineer |
