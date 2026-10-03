# QualLoop — Understanding of the Blueprint (Phase 0)

Written by the orchestrator from `docs/blueprint/Supplier_Quality_OS_Blueprint_FINAL.md` (frozen),
`docs/build/PHASES.md` and `docs/design/DESIGN_SPEC.md`. `§` = blueprint section.
Nothing here changes the spec. Ambiguities are listed in §6 of this file and copied to
`docs/build/OPEN_QUESTIONS.md`; none are resolved silently.

---

## 1. The control loop in my words

A plant receives material from a supplier (GRN / lot). An inspector finds a defect and logs an NCR on a
phone in ≤ 30 s, with a photo and a rejected quantity **per defect** — each defect becomes a
`defect_event`, the only place rejected quantity lives (§11). The SQE contains the problem and decides
what happens to the material (disposition). At the **SCAR decision gate** the system recommends
SCAR / Monitor / Local close / Add to existing SCAR from severity, repeats, cost and customer impact; the
SQE decides and the decision is logged (§9 C6). A SCAR (which may cover many NCRs) is issued; the supplier
contact gets a WhatsApp/email link, proves identity with an OTP, and fills an 8D (D3–D7) on a phone with no
account (§9 C7). The SQE accepts or sends back (new revision each time). Money is tracked in parallel:
NCR cost lines → debit note allocations → recoveries / write-offs, every rupee traceable (§10).
When the SCAR is accepted, **effectiveness** watches the next lots AND a time window for the same defect
signature (§9 C8); pass → close, signature match → reopen. Metrics (§12), the Supplier Quality Score (§14)
and the Risk engine (§15) are recomputed from these records, always with sample/coverage/freshness and
"N/A" when data is insufficient. The next action is surfaced in **My Work** (§16).
A parallel, slower loop handles supplier documents and certificates: requirements → request → upload →
AI extraction → human review → computed validity → reminders/escalations → compliance & risk (§7.3, §7.4, §8 C10).

Hard principles: suppliers never need an account; AI only suggests, from workers, never decides or touches
money; every state change is an explicit command with audit + outbox; computed states (validity,
exceptions, due-status, compliance) are never stored; closed periods are frozen (as-of rule).

---

## 2. Entities (§6) — grouped

| Group | Tables | Notes |
| --- | --- | --- |
| Platform §6.1 | tenants, plants, users, activity_log, outbox_events | tenant settings json: SLA hours, default PPM target, min samples, score weights |
| Masters §6.2 | suppliers, supplier_contacts, contact_consents, customers, parts, customer_parts, supplier_parts | supplier status = human decision; contacts have identity lifecycle; parts↔customers M:N |
| Receipts & quality §6.3 | grn_receipts, defect_codes, defect_events, ncrs, defect_event_attributions, ncr_photos, ncr_containment, ncr_costs, scars, ncr_scar_links, scar_responses, scar_evidence, scar_reviews, effectiveness_checks, debit_notes, debit_note_allocations, recoveries, recovery_allocations, write_offs | defect_events = single source of rejected qty; attributions append-only; money chain |
| Documents §6.4 | documents, certificates, document_requirements, supplier_requirements, certificate_exceptions, ai_extractions | validity & exceptions computed; exceptions UI R1.1 |
| Supplier access & messaging §6.5 | magic_links, supplier_sessions, messages, tasks | token hash only; session scoped to one object |
| Measurement & risk §6.6 | supplier_scores_monthly, risk_events, supplier_risk_current, risk_overrides, quality_targets | snapshots immutable; overrides UI R1.1; quality_targets hierarchy R1.1 |
| Imports §6.7 | import_batches, import_records | file hash + row hash; duplicates reported, never merged |

Total: 48 tables. Common columns on every table: `id` (UUIDv7 per CLAUDE.md), `tenant_id`, `created_at`,
`created_by`, `updated_at`, `updated_by`; RLS on `tenant_id` from the first migration (§6, §24.1.1).
Numbering: `NCR-{plant}-{YYMM}-{seq}`, `SCAR-{YYMM}-{seq}`, `DN-{YYMM}-{seq}` (§6).

---

## 3. State machines (§7)

All transitions are command endpoints (§24.2), authorised, writing `activity_log` + `outbox_events` in one
transaction. No generic "update status" endpoint (§7).

### 3.1 NCR (§7.1)
```
OPEN → CONTAINED → AWAITING_SCAR | MONITOR | LOCAL_CLOSE
AWAITING_SCAR → LINKED_TO_SCAR → VERIFICATION → CLOSED
MONITOR → CLOSED        (reason recorded)
LOCAL_CLOSE → CLOSED    (minor, reason recorded)
any open state → CANCELLED (reason; Admin or can_approve)
CLOSED → (reopen command with reason, §7.5 / §24.2)  — target state unspecified, see A-05
```
Disposition: return to supplier / rework / sort and use / scrap / use-as-is (use-as-is needs `can_approve`).

### 3.2 SCAR (§7.2)
```
DRAFT → ISSUED → RESPONSE_STARTED → RESPONSE_SUBMITTED → UNDER_REVIEW
UNDER_REVIEW → SENT_BACK → RESPONSE_STARTED (revision + 1)
UNDER_REVIEW → ACCEPTED → EFFECTIVENESS → CLOSED (passed | closed_no_data with reason)
EFFECTIVENESS → REOPENED (failed) → RESPONSE_STARTED
EFFECTIVENESS → EFFECTIVENESS (extend: new window, reason, extensions + 1; max 2)
DRAFT | ISSUED → CANCELLED (reason)
```

### 3.3 Certificate review status (§7.3) — stored
`PENDING_REVIEW → APPROVED | REJECTED`; `APPROVED → SUPERSEDED` (newer version of same doc type approved).
Validity (computed, APPROVED only, plant-timezone today): valid (> +60) · expiring_60 (+30 < e ≤ +60) ·
expiring_30 (+7 < e ≤ +30) · expiring_7 (today ≤ e ≤ +7) · expired (e < today).

### 3.4 Supplier requirement (§7.4) — stored status + computed compliance
First-time: `NOT_REQUESTED → REQUESTED → PENDING_REVIEW → APPROVED`; overdue = REQUESTED and due_at passed
(computed); rejected upload → REQUESTED with new due_at. Renewal: status stays APPROVED; renewal_requested_at /
renewal_due_at set at expiring_60 or on SQE request; replacement approved → becomes current, old SUPERSEDED;
replacement rejected → current unchanged, renewal_due_at reset. `status = approved` ≠ compliant.
Exception = computed (`certificate_exceptions.valid_until ≥ today`).

### 3.5 Effectiveness check (§6.3, §9 C8)
`pending → passed | failed | closed_no_data`; extend keeps `pending` with new window, `extensions + 1` (≤ 2).

### 3.6 Others with enumerated statuses (transitions NOT defined in the spec — see ambiguities)
- Supplier status: approved / approved_with_action_plan / on_watch / blocked / inactive — any→any via
  `change-status` with reason + `can_approve` (§15.6).
- Debit note: raised / accepted / partly_recovered / recovered / disputed / written_off (A-30).
- Message: queued → sent → delivered → read → failed / expired (§17.4).
- Import record: imported / duplicate / rejected / unmapped / review. Import batch status: values unspecified (A-41).
- Defect event attribution_status: attributed / unattributed / superseded.
- Magic link / supplier session: active / expired / revoked (computed from timestamps).

---

## 4. Invariants (with §)

### Platform & integrity
| # | Invariant | § |
| --- | --- | --- |
| I-01 | Every table has tenant_id; RLS on tenant_id from the first migration; tenant A cannot read/write tenant B (API, ORM, worker, files) | §6, §21.2, §24.1.1 |
| I-02 | Every state change goes through a command: authorised, writes activity_log (before/after/reason/actor_type/session/ip) + outbox event in the same transaction | §7, §22.2, §24.1.2 |
| I-03 | No generic update-status endpoint | §7 |
| I-04 | NCR, SCAR, debit note, certificate never hard-deleted; cancel with reason | §7.5 |
| I-05 | Closed NCR/SCAR immutable; corrections only via reopen with reason | §7.5 |
| I-06 | Debit amounts, dispositions, certificate approvals, supplier status editable only via commands with before/after + reason | §7.5 |
| I-07 | Score snapshots immutable | §7.5, §14.5 |
| I-08 | Every supplier response revision kept, never overwritten | §7.5, §9 C7 |
| I-09 | Masters archived (archived_at), never deleted if referenced | §7.5 |
| I-10 | External effects only from workers, idempotent (idempotency_key), retried with exponential backoff, dead-letter after 5 with alert | §22.2 |
| I-11 | AI calls only from background jobs via ai/providers; AI never approves/rejects certs, closes NCR/SCAR, changes supplier status, overrides risk, calculates/edits money, deletes records | §20.1, §24.1.3 |
| I-12 | Every workflow works with AI unavailable | §20.1 |
| I-13 | No WhatsApp logic outside notifications/ | §17.2 |
| I-14 | Every supplier flow works over email + web link alone; opt-out changes channel, never blocks | §4.10, §17.1, §17.3 |

### Rejected quantity (§11)
| # | Invariant | § |
| --- | --- | --- |
| I-20 | Every physically rejected unit = exactly one active defect_event; metrics never add NCR qty to ERP qty nor take a max | §11.1 |
| I-21 | NCR qty_rejected = Σ attributed defect_events of the NCR (derived) | §6.3 |
| I-22 | NCR capture → attributed event with code (category-only allowed); ERP import → unattributed, no code; manual → attributed with code | §11.2, §8 C5 |
| I-23 | Each attribution decision writes a defect_event_attributions row; never edited, only superseded | §6.3, §11.3 |
| I-24 | Four decisions: same (ERP superseded), same-qty-corrected (one superseded, quantities + difference + reason stored), different defect (both count), internal (ERP superseded, excluded) | §11.3 |
| I-25 | System never attributes on its own; it only suggests (same receipt + equal qty) | §11.3 |
| I-26 | canonical vs unreconciled per receipt per §11.4 formula; PPM and all rates use canonical only; unreconciled shown separately, labelled "awaiting reconciliation" | §11.4, §12 |
| I-27 | PPM "Provisional" when supplier has unreconciled qty in period | §11.4 |
| I-28 | Unattributed events never count toward repeats, signatures, effectiveness | §11.4 |
| I-29 | Defect events without receipt excluded from PPM until matched | §11.4 |
| I-30 | Receipts unique on (tenant, plant, grn_no, part_id, lot_no) | §6.3 |
| I-31 | ERP rejections are imported as separate rows, never as a column added to NCR quantities | §8 C4 |

### Imports (§8 C3)
| I-35 | Same file twice flagged before processing (file hash); natural keys + row hash; duplicates reported never merged; partial imports need explicit confirmation; report with reason per row | §8 C3 |

### NCR / SCAR / effectiveness
| # | Invariant | § |
| --- | --- | --- |
| I-40 | Use-as-is disposition requires can_approve | §2.2, §8 C5 |
| I-41 | NCR cancel needs reason and Admin or can_approve | §7.1 |
| I-42 | Defect signature = supplier + part + defect code (fallback category); repeat = same signature within 90 days | §8 C5 |
| I-43 | Critical → SCAR mandatory; Major → required unless waived with reason; Minor → optional, required on 2nd repeat in 90 days | §9 C6 |
| I-44 | SLA due dates in calendar hours, plant timezone; response times only from explicit scars timestamps, never updated_at | §9 C6 |
| I-45 | first_response_at = first supplier action of any kind; final_response_at = first complete D3–D7 submission, never moved by later revisions | §6.3 |
| I-46 | D4 requires occurrence, escape and systemic cause | §9 C7 |
| I-47 | Send-back → new revision; all revisions retained | §9 C7 |
| I-48 | Effectiveness: min lots AND min days (+ optional min qty); pass only with criteria met and no signature match; fail only on attributed signature match; different defect does not fail; unattributed ERP rejection on a watched receipt holds; never pass/fail without data | §9 C8 |
| I-49 | Extend max 2, then only close-no-data; both need reason; closed_no_data counted separately from passed, shown "not verified" | §9 C8 |

### Supplier access (§9 C7, §21.2)
| # | Invariant | § |
| --- | --- | --- |
| I-50 | 32-byte random token; only hash stored | §9 C7 |
| I-51 | OTP to the contact's verified mobile (or email) before session | §9 C7 |
| I-52 | Session scoped to ONE object, 7 days; link re-openable 30 days with new OTP | §9 C7 |
| I-53 | Revoke on contact disabled/replaced, SCAR closed/cancelled, manual revoke; expired/revoked/used-up links fail; disabled contact's sessions fail | §9 C7, §21.2 |
| I-54 | Supplier never sees internal risk, score, costs, debit amounts, internal comments, other NCRs/SCARs, other suppliers | §9 C7, §21.2 |
| I-55 | Contact unverified for 180 days re-verified by OTP before receiving new links | §8 C2 |
| I-56 | Replace contact → old links/sessions revoked, open SCARs reassigned | §8 C2 |

### Money (§10)
| # | Invariant | § |
| --- | --- | --- |
| I-60 | Debit note cannot be saved until fully allocated: Σ allocations = debit note amount | §6.3, §10 |
| I-61 | Allocations only to cost lines with recoverable = true | §6.3, §10 |
| I-62 | Σ allocations per cost line ≤ cost line amount | §6.3 |
| I-63 | Per allocation: recovered + written_off ≤ allocation amount — app command AND DB constraint trigger | §6.3, §10 |
| I-64 | outstanding never negative | §10 |
| I-65 | Recovery auto-allocated pro-rata to remaining outstanding, never above; rounding remainder to largest outstanding; manual override within the same limit | §6.3 |
| I-66 | Changing an allocation after recovery requires a command with reason | §10 |
| I-67 | Cohort view and cash view never mixed; Recovery % only in cohort view = recovered ÷ gross exposure; no % in cash view | §10 |
| I-68 | Money entered by people; AI never calculates or edits money | §10, §20.1 |
| I-69 | Money stored as BIGINT paise (CLAUDE.md §6) | CLAUDE.md |

### Documents (§7.3, §7.4, §13)
| # | Invariant | § |
| --- | --- | --- |
| I-70 | Certificate validity never stored; computed per read from expiry_date and plant-timezone today; only APPROVED have validity | §6.4, §7.3 |
| I-71 | Requirement compliance computed from current_certificate_id + validity + active exception; never from status alone | §7.4 |
| I-72 | Exception state computed (valid_until ≥ today); max 90 days; can_approve; suppresses CERT_EXPIRED / CERT_MISSING, not reminders | §7.4, §13 |
| I-73 | One supplier_requirements row per supplier per mandatory doc type, created on supplier create / category change as not_requested | §6.4, §8 C10 |
| I-74 | Rejected renewal keeps current_certificate_id; rejected first-time upload → REQUESTED with new due_at | §7.4 |
| I-75 | Daily scan emits CERTIFICATE_VALIDITY_CHANGED / REQUIREMENT_OVERDUE only when computed state differs from last successfully sent message state; twice = no duplicate; skipped day = sent next run | §22.3, §24.1.4 |
| I-76 | Upload PDF/JPG/PNG ≤ 20 MB, content-type check + virus scan; signed URLs ≤ 15 min; private buckets | §20.2, §21.1 |
| I-77 | AI extraction stores model, versions, source hash, spans, reviewer corrections | §20.2 |

### Metrics, score, risk (§12, §14, §15)
| # | Invariant | § |
| --- | --- | --- |
| I-80 | Every metric is per supplier (and supplier-part), per plant, for an explicit period | §12 |
| I-81 | Formulas exactly per §12 table (PPM, qty rejection %, lot rejection rate, unreconciled, PPM by defect, repeats, disruptions, premium freight, SCAR on-time %, late completions, time to first response, time to acceptance, document compliance %, recovery %, capture time) | §12 |
| I-82 | SCAR due-status exactly one of on_time/late/overdue (not-yet-due and cancelled excluded), evaluated as of period end; open overdue stays in denominator | §12 |
| I-83 | Min sample: PPM/rejection ≥ 5 receipts AND ≥ 1,000 units; SCAR metrics ≥ 1 SCAR due; else "N/A — insufficient data" | §12.1 |
| I-84 | Every metric carries sample, coverage, freshness; every number drills down with a "How this was calculated" payload | §4.6–7, §12.1, §16 |
| I-85 | Score: weights 50/20/15/15; component N/A not 100; re-weight across available; Quality N/A → no total, no grade | §14.1, §14.2 |
| I-86 | Grades A ≥ 85, B 70–84, C 50–69, D < 50; never show grade alone | §14.3 |
| I-87 | Insufficient-data suppliers never ranked above measured ones (listed separately) | §14.3, §16 |
| I-88 | Monthly snapshot on 1st with formula_version; immutable; weight/target changes affect future only | §14.5 |
| I-89 | As-of rule: closed period uses only event timestamps ≤ period_end; later events appear in their own period; historical data corrections listed as "Corrections to earlier periods" | §14.5 |
| I-90 | Risk recomputed from active conditions (not running total); conditions age out | §15.1 |
| I-91 | Rule points/caps per §15.2; total cap 100; Low 0–29, Medium 30–59, High ≥ 60 | §15.2 |
| I-92 | Each active condition is a risk_events row; cleared → active=false + cleared_at; reasons generated from rule_code + params (reproducible) | §15.3 |
| I-93 | Override keeps system score; both shown | §15.5 |
| I-94 | Risk never changes supplier status; may only suggest on_watch after 2 consecutive High months | §15.6 |

---

## 5. Things outside the blueprint that other sources add (flagged, not resolved)

| Item | Source | Note |
| --- | --- | --- |
| UUIDv7, BIGINT paise, timestamptz | CLAUDE.md §6 | Spec says "uuid" and `amount_inr`; CLAUDE.md refines. Column naming decision needed (A-01) |
| Google login, password reset by email OTP | PHASES P01 | Not in §21.1. Priority 4 source; additive. A-46 |
| ClamAV container for virus scan | PHASES P01 | Needs its own server/container → CLAUDE.md §5 ask-first. A-47 |
| Minimal billing | PHASES P09 | Not in Part A beyond §26.4 pricing hypotheses. A-48 |
| OpenTelemetry tracing | PHASES P01 | §22 says error tracking/logs/uptime/queue dashboard; OTel is a HOW choice |

---

## 6. Ambiguities found (NOT resolved — each needs a human decision or an ADR-recorded conservative default)

### Data model & platform
- **A-01** Money: spec columns are `amount_inr`; CLAUDE.md requires BIGINT paise. Keep name `amount_inr` holding paise, or rename to `amount_paise`? (§6.3 vs CLAUDE.md §6)
- **A-02** `created_by` / `updated_by` on rows created by a supplier session, system job or AI — type and reference target (users.id only?) unspecified. (§6, §6.1 actor_type)
- **A-03** Users: is a user bound to exactly one tenant? Is email unique globally or per tenant? (§6.1)
- **A-04** `users.plant_ids`: does it restrict what a user can see/do (plant-level authorisation), or is it just default filtering? (§6.1)
- **A-06** Supplier initial `status` on create/import is not specified. (§6.2, §15.6)
- **A-07** `activity_log` / `outbox_events` are append-only, yet "every table" has `updated_at/updated_by`. Keep columns, or exempt append-only tables? (§6, §6.1)
- **A-08** Certificates, requirements and supplier documents are supplier-level (no plant_id) but validity is computed with "today in the plant timezone". Which timezone for a multi-plant tenant? (§7.3)
- **A-09** Score snapshot is per supplier **per plant** but document compliance is supplier-level. Use the same document score for every plant? (§6.6, §14.1)
- **A-10** "Owner" / "the SQE": no owner/assignee column on NCR, SCAR or supplier, yet notifications go to "SQE", QueueRow shows Owner and My Work is per user. Who is the SQE for a given object? (§6.3, §16, §17.2, DESIGN_SPEC)
- **A-11** "Head of Quality" recipient = all users with `can_approve`? (§2.2, §17.2)
- **A-12** Supplier contact language (en/hi) preference has no column; how is template language chosen? (§6.2, §17.2)

### NCR
- **A-05** NCR `reopen` (§24.2, §7.5) — target state after reopen is not in the §7.1 diagram; effect on its defect events.
- **A-13** NCR cancelled: are its defect events superseded/excluded from metrics? (§7.1, §11.1)
- **A-14** Must every NCR pass through CONTAINED, even when no containment is needed? Is `contain` with zero actions allowed? (§7.1)
- **A-15** When does an NCR move LINKED_TO_SCAR → VERIFICATION → CLOSED — automatically following SCAR state (EFFECTIVENESS / CLOSED) or by separate NCR commands? What happens to linked NCRs when the SCAR is REOPENED or CANCELLED? (§7.1, §7.2, §9 C8)
- **A-16** "Add to existing SCAR" decision: does the NCR go CONTAINED → LINKED_TO_SCAR directly (skipping AWAITING_SCAR)? (§7.1, §9 C6)
- **A-17** In which NCR states is `dispose` allowed, and can disposition change later (command with reason)? (§8 C5, §7.5)
- **A-18** An NCR with several defects: which signature drives `is_repeat`, SCAR grouping suggestion and the decision gate — primary_defect_code_id or any defect? (§6.3, §8 C5)
- **A-19** Repeat window: across plants (signature excludes plant)? Inclusive 90 days on `detected_at`? Cancelled NCRs counted? (§8 C5)
- **A-20** Minor "required on 2nd repeat in 90 days": does that mean the 2nd occurrence (first repeat) or the 3rd occurrence? (§9 C6)
- **A-21** NCR capture "pick only the category" → attributed defect_event with null `defect_code_id`. §11.2 says NCR events have a code. Confirm category-only attributed events are allowed. (§8 C5, §11.2)
- **A-22** Cost lines "expected before closure": a soft warning or a hard block on close? (§8 C5)
- **A-23** Major SCAR "waived with reason": who may waive (can_approve?) and where is it recorded when no SCAR exists (`scars.waived_reason` implies a SCAR row)? (§6.3, §9 C6)
- **A-24** Matching command for receipt-less defect events (suggested by supplier + part + lot) is not in §24.2. (§11.4)
- **A-25** Historical NCR import (`import_batches.entity = ncrs`): what `defect_events.source` do imported NCRs get (enum is ncr_capture / erp_import / manual)? (§6.3, §6.7)

### SCAR
- **A-26** Trigger for ISSUED → RESPONSE_STARTED (link opened? OTP verified? first draft save?) and what counts as "first supplier action of any kind" for `first_response_at`. (§6.3, §7.2)
- **A-27** RESPONSE_SUBMITTED → UNDER_REVIEW: automatic or an SQE "start review" action (no command listed)? (§7.2, §24.2)
- **A-28** SCAR covering NCRs of different severities: SCAR severity = highest? Do due dates change when a more severe NCR is added? Can a SCAR link NCRs from different plants (SCAR has one plant_id)? (§6.3, §9 C6)
- **A-29** After REOPENED → RESPONSE_STARTED: revision + 1? New due dates? `final_response_at` unchanged? Effect on SCAR on-time %. Is a new effectiveness_checks row created after re-acceptance? (§7.2, §12)
- **A-31** Containment due measured from `issued_at` or NCR `detected_at`? (§9 C6)
- **A-32** Internal vs supplier-visible review comments: `scar_reviews.comment` is single. Supplier must see "review comments addressed to them" but never "internal comments". No field distinguishes them. (§6.3, §9 C7)
- **A-33** "Message thread for this SCAR" with the supplier: `messages` models outbound notifications; inbound supplier messages / replies have no model. (§6.5, §9 C7)
- **A-34** `ncr_scar_links.relationship` primary/related: exactly one primary per SCAR? (§6.3)
- **A-35** Closed SCAR reopen for corrections (§7.5) has no command in §24.2 (only effectiveness-failure REOPENED).

### Supplier access
- **A-36** "Used-up links fail" (§21.2) vs "link valid 30 days to re-open with a new OTP" (§9 C7). What makes a link "used up" (OTP attempt limit? object closed?) (§9 C7, §21.2)
- **A-37** Document upload links: one link per requirement or one per supplier bulk request ("scoped to ONE object")? (§6.5, §8 C10)
- **A-38** OTP when contact has neither verified mobile nor verified email: send to unverified email? Block? (§9 C7, §8 C2)

### Money
- **A-30** Debit note status transitions (raised / accepted / partly_recovered / recovered / disputed / written_off) are undefined: which are derived from balances, which are commands (accept, dispute)? Status when partly recovered + rest written off? (§6.3)
- **A-39** Recovery larger than the debit note's total outstanding → reject? Pro-rata rounding tie-break when two allocations share the largest outstanding. (§6.3)
- **A-40** "Changing an allocation after recovery requires a command with reason" — no endpoint in §24.2; also debit note cancel ("cancel with reason", §7.5) has no endpoint. (§10, §7.5)

### Imports
- **A-41** `import_batches.status` values not enumerated. Re-import of a row with the same natural key but changed values (e.g. receipt qty): duplicate, review, or correction? (§6.7, §8 C3)
- **A-42** ERP rejection natural key mentions "ERP rejection reference" — no column holds it on defect_events (only source_ref = import_record_id). (§8 C3, §6.3)

### Documents
- **A-43** Certificates without an expiry date (quality agreement, RoHS/REACH declaration): validity? compliance? (§7.3, §8 C10)
- **A-44** Supplier category change: what happens to existing requirements that are no longer mandatory for the new category? (§8 C10)
- **A-45** `renewal_due_at` value on renewal request (renewal_requested_at + grace_days?). Requirement in PENDING_REVIEW past due_at: neither "due" for compliance nor CERT_MISSING — indefinitely pending? (§7.4, §12, §15.2)
- **A-49** Is CERT_EXPIRING limited to mandatory requirements (CERT_EXPIRED says "mandatory")? (§15.2)
- **A-50** In R1 the exceptions table exists but has no UI; exceptions cannot be created until R1.1 — confirm (no seed/admin path). (§5.2, §13)

### Metrics, score, risk
- **A-51** As-of rule for PPM: receipts selected by `grn_date` in period — which defect events count: by `detected_at`, `created_at` or attribution `decided_at` ≤ period_end? (§12, §14.5)
- **A-52** Period boundaries = calendar month in plant timezone? Snapshot "on the 1st" in plant timezone? (§14.5)
- **A-53** Minimum sample for Repeat/Disruption and Document components is not defined. (§12.1, §14.2)
- **A-54** Quality score when target = 0 (division by zero) and exact interpolation; grade rounding (84.5 → A or B?). (§14.1, §14.3)
- **A-55** `coverage_pct` on the snapshot: which of the three §12.1 coverage measures? (§6.6, §12.1)
- **A-56** PPM_RISING "3-month average": the 3 months before the month in question, each with min sample? (§15.2)
- **A-57** SUPPLIER_NO_RESPONSE "open request": SCARs issued, document requests, or both; "supplier action" definition. (§15.2)
- **A-58** Risk `trend` up/flat/down compared with what (previous calculation, 30 days ago, last month)? (§6.6)
- **A-59** "Suggest on watch after two consecutive months at High" — no table stores monthly risk level history (`supplier_risk_current` only). (§15.6, §6.6)
- **A-60** Risk scope: per supplier (no plant_id on risk tables) while PPM_HIGH etc. are per plant. Aggregate across plants? (§6.6, §15.2)
- **A-61** Time to first response / acceptance medians: over SCARs issued in the period, or with the event in the period? (§12)
- **A-62** My Work "3 suppliers turned High risk" — window (since last login, 7 days, this month)? (§16)

### AI & notifications
- **A-63** 8D review assist output and NCR category suggestion have no storage table (`ai_extractions` is document-only). (§20.3, §20.4, §6)
- **A-64** Voice-to-text at capture is interactive, but AI calls are allowed only from background jobs. Use the device/browser speech API (not the AI layer), or async? (§20.4, §24.1.3)
- **A-65** SMS provider and whether SMS is in R1 scope at all ("optional"). (§17.1)
- **A-66** Daily scan "most recent successfully sent message": per channel or any channel; per recipient? (§22.3)

### Scope additions from PHASES.md (need confirmation)
- **A-46** Google login (P01) not in blueprint §21.1.
- **A-47** ClamAV virus-scan container = a dependency with its own server → CLAUDE.md §5 requires human approval.
- **A-48** Minimal billing (P09) — not specified in Part A.
