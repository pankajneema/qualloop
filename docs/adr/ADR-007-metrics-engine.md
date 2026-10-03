# ADR-007 — Metrics engine: canonical rejected quantity, cohort vs cash, as-of snapshots, computed states

- Status: Accepted (2026-10-03)
- Spec: §4.6–4.7, §7.3, §7.4, §10, §11.4, §12, §12.1, §13, §14, §15

## Context
Numbers must be exact, reproducible and explainable: rejected quantity only from defect events (§11), PPM on canonical
quantity with provisional labelling, two money views never mixed (§10), closed periods frozen as of period end (§14.5),
and validity / exception / due-status / compliance computed on read, never stored (§7.3, §7.4, §12).

## Options considered
| Option | Pros | Cons |
| --- | --- | --- |
| A. Python loops over ORM objects | easy to write | slow, N+1, hard to explain |
| B. **Set-based SQL (views + SQL functions parameterised by `as_of`) called from typed Python calculators** | fast, one definition reused by API, snapshots, reports, drill-downs | SQL skill; needs parity tests |
| C. Materialised fact tables from day one | fast reads | staleness, invalidation complexity; not needed at Stage 1 |

## Decision
Option B; option C only on trigger (SCALING.md S-10).

| Element | Implementation |
| --- | --- |
| Canonical quantity | `receipt_rejections_as_of(cutoff)` SQL function: per receipt, attributed / unattributed sums of events active as of cutoff; §11.4 overlap rule; `v_receipt_rejections` = same with cutoff = now |
| As-of event state (M2) | `defect_event_state_as_of(cutoff)` (DATA_MODEL.md §8) covers all three event kinds:
- **ERP events** start `unattributed` and then follow their latest attribution row with `decided_at < cutoff`.
- **NCR events** are `attributed` from creation. Each becomes `superseded` from the `decided_at` of the qty-corrected attribution that superseded it, and is inactive if its NCR was cancelled before the cutoff.
- **Replacement events** exist from their `created_at`, which equals that attribution's `decided_at`.

The deferred trigger requires an attribution row for **any** status, code or NCR change of **any** event, so every state change is reconstructable. Quantities are immutable, so no quantity history is needed. Test: `test_as_of_qty_corrected_counts_once` |
| Qty corrections | surviving event = the event whose qty equals `accepted_qty`; if neither, a new attributed event (source `manual`, `source_ref` = attribution id) supersedes both (A-68) — quantities are never updated in place |
| PPM / rates | receipts with `grn_date` in period; numerator canonical only; `provisional = unreconciled > 0` |
| Min sample | from `tenants.settings.min_sample` (defaults §12.1); below → `value = null`, `na_reason = 'insufficient_data'` |
| Trust signals | every calculator returns `MetricValue{value, sample{lots, units, scars}, coverage{supplier_part_mapped, rejected_linked_to_receipt, rejected_attributed}, freshness{last_import_at, calculated_at}, provisional, unreconciled_qty, how}` |
| Explain payload | `how` = formula id, period, cutoff, input record ids (paged), exclusions with reasons; drill-down records must sum to value (test) |
| SCAR due-status | `scar_due_status(final_due_at, final_response_at, status, as_of)`: cancelled → excluded; `final_due_at > as_of` → not_yet_due; `final_response_at ≤ final_due_at` → on_time; `final_response_at` in (due, as_of] → late; else overdue |
| Late completions | SCARs with `final_response_at` in period and `final_due_at` before period start |
| Money views | `v_cost_line_balances`; cohort = lines with `incurred_on` in period, settlements up to "to date" (live) or cutoff (snapshot); cash = recoveries with `recovered_on` in period grouped by `incurred_on` month; no % in cash view |
| Validity | `certificate_validity(expiry, today)`: expired if `expiry < today`; expiring_7 if `≤ today+7`; expiring_30 if `≤ today+30`; expiring_60 if `≤ today+60`; else valid. Only for `approved` |
| Compliance | `requirement_compliance(today)`: exception active (`valid_until ≥ today`) → compliant; approved + current cert validity ≠ expired → compliant; due = approved ∪ under exception ∪ requested with `due_at < now` (∪ pending_review past due, A-45); rest pending |
| Score | Python `score.py` over `MetricValue`s: weights from settings, N/A re-weighting, no total when Quality N/A, grade from `round(total)` half-up (A-54), `formula_version` constant |
| Snapshots | job on 1st 00:30 plant local; computes with `as_of = cutoff` and, for date-based functions (`certificate_validity`, `requirement_compliance`, exception activity), **`today = period_end`** (m1), never the run date; inserts with `inputs` jsonb; unique `(tenant, supplier, plant, period_start)`; append-only |
| Corrections to earlier periods | `activity_log` rows with `created_at ≥ cutoff` whose object is an input of the closed period (receipts, defect events, attributions, cost lines) → listed with before/after in the next report |
| Risk | one evaluator per rule_code reading the same calculators; recompute = upsert active conditions, clear missing ones (`active=false, cleared_at`); total capped 100; reasons rendered from `rule_code + params` templates (en/hi) |
| Parity | Python reference implementations of each formula used only in tests (property tests compare SQL vs reference on random fixtures) |

## Consequences
- One SQL definition per formula; API, PDF and snapshots cannot disagree (P08 test "report PDF equals API").
- Computing as-of from append-only attribution rows needs no history tables.
- Known limitation: a re-decision that changes an ERP event's defect code after cutoff is reflected with the latest code
  in the as-of calculation of PPM-by-defect (quantity totals are unaffected). Documented in the explain payload.

## Revisit when
- Metrics endpoint p95 > 1 s or My Work p95 > 500 ms after index tuning (→ S-10), or
- snapshot job for all tenants exceeds 30 min.
