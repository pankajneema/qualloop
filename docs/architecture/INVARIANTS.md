# QualLoop — Invariants Register (Phase 0)

Every invariant in blueprint §6, §7, §9 C6–C8, §10, §11, §12, §14, §15, §21.2, §22.2, §22.3, §24.1 with its
enforcement point and the planned test name. QA writes these tests from the spec; names are contracts the verifier
greps for. Test locations: `api/tests/unit/<module>/`, `api/tests/integration/<module>/`, `api/tests/security/`,
`web/e2e/`. `docs/understanding.md` I-xx ids are cross-referenced in the last column.

Enforcement codes: **DB** = constraint / trigger / RLS / grant (DATA_MODEL.md §0.6) · **CMD** = command handler
(ADR-003) · **WRK** = worker / scheduled job · **QRY** = metrics/read-model query or SQL function · **SCH** = response
schema allow-list · **CI** = static check in CI (import-linter, grep rule).
Where both DB and CMD are listed, both must have a test (`_db` and `_api` suffixes).

---

## 1. Platform, audit, reliability (§6, §7, §7.5, §22.2, §22.3, §24.1)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-PLT-01 | Every table has `tenant_id`; RLS enabled + forced from the first migration; tenant A cannot read or write tenant B rows | §6, §21.2, §24.1.1 | DB (RLS T, composite FKs, NOBYPASSRLS role) | `test_every_table_has_tenant_id_and_forced_rls`, `test_tenant_a_cannot_read_tenant_b_rows_raw_session`, `test_tenant_a_cannot_insert_row_for_tenant_b`, `test_composite_fk_rejects_cross_tenant_reference` | P01 (+ each phase adds its tables to the parametrised test) | I-01 |
| INV-PLT-02 | Unset tenant context sees zero rows and cannot write | §24.1.1 | DB | `test_no_tenant_context_returns_zero_rows`, `test_no_tenant_context_insert_rejected` | P01 | I-01 |
| INV-PLT-03 | Workers set tenant context per job; a job cannot touch another tenant | §21.2 | WRK (job wrapper) + DB | `test_worker_job_runs_with_job_tenant_context`, `test_worker_job_cannot_read_other_tenant` | P01 | I-01 |
| INV-PLT-04 | Every state change goes through a command that authorises, writes `activity_log` (before/after/reason/actor_type/session/ip) and `outbox_events` in the same transaction | §7, §22.2, §24.1.2 | CMD (base handler) | `test_command_writes_activity_log_and_outbox_in_same_transaction`, `test_command_failure_rolls_back_activity_log_and_outbox`, `test_activity_log_records_actor_session_and_ip` | P01 | I-02 |
| INV-PLT-05 | `activity_log` is append-only for the app role | §7.5, §21.1 | DB (grant CR + trigger) | `test_activity_log_update_rejected_db`, `test_activity_log_delete_rejected_db` | P01 | I-02 |
| INV-PLT-06 | No generic "update status" endpoint; status columns change only via named commands | §7 | CI (route scan: no PATCH/PUT touching `status`) + CMD | `test_no_route_accepts_status_field_outside_commands` | P01 | I-03 |
| INV-PLT-07 | NCR, SCAR, debit note, certificate never hard-deleted; no DELETE on any domain table | §7.5 | DB (no DELETE grant) | `test_app_role_has_no_delete_privilege_on_domain_tables` | P01 | I-04 |
| INV-PLT-08 | Masters archived via `archived_at`, never deleted; archived masters excluded from pickers but kept in history | §7.5 | DB + CMD | `test_supplier_archive_sets_archived_at_and_keeps_references`, `test_archived_part_hidden_from_capture_search` | P02 | I-09 |
| INV-PLT-09 | `users.plant_ids` reference plants of the same tenant | §6.1 | DB trigger | `test_user_plant_ids_must_exist_in_tenant_db` | P01 | — |
| INV-PLT-10 | Viewer cannot call any command; `can_approve` required where flagged | §2.2 | CMD (permission decorator) | `test_viewer_cannot_call_any_command` (parametrised over all commands), `test_can_approve_commands_reject_without_flag` | P01 + each phase | — |
| INV-PLT-11 | External effects (WhatsApp, email, SMS, AI, PDF) only from workers, idempotent via `idempotency_key` | §22.2 | CI (import-linter: providers not importable from `api`/`commands`) + WRK | `test_api_layer_cannot_import_provider_clients`, `test_external_send_carries_idempotency_key` | P01 | I-10 |
| INV-PLT-12 | Outbox event processed exactly once under concurrent dispatchers | §22.2 | WRK (`FOR UPDATE SKIP LOCKED`) | `test_outbox_event_processed_once_with_two_concurrent_dispatchers` | P01 | I-10 |
| INV-PLT-13 | Retries use exponential backoff; dead-letter after 5 attempts with alert | §22.2 | WRK | `test_outbox_retry_backoff_increases_exponentially`, `test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted`, `test_job_dead_lettered_after_5_attempts` | P01 | I-10 |
| INV-PLT-14 | Command idempotency: same Idempotency-Key + same body replays; different body → 422 | §22.2 | CMD + DB (`idempotency_keys`, A-73) | `test_idempotency_key_replays_original_response`, `test_idempotency_key_reuse_with_different_body_rejected` | P01 | — |
| INV-PLT-15 | Every §22.3 event is emitted by the command/job that causes it | §22.3 | CMD/WRK | `test_event_catalogue_every_22_3_event_has_emitter` + per-event tests named `test_<command>_emits_<EVENT>` in each phase | P01–P07 | — |
| INV-PLT-16 | Migrations reversible: upgrade → downgrade → upgrade | §24.1.1 | CI | `test_migrations_up_down_up` | P00/P01 | — |
| INV-PLT-17 | Seed demo tenant: 50 suppliers, 120 parts, 3 months receipts, 40 NCRs, 15 SCARs (multi-NCR, overdue, one reopened), 60 certificates | §24.1.6 | seed script | `test_demo_seed_meets_24_1_counts` | P09 | — |
| INV-PLT-18 | SECURITY DEFINER functions use `search_path = pg_catalog, public, pg_temp`, schema-qualified tables, EXECUTE only for `qualloop_app`; `PUBLIC` has no TEMP on the database and no CREATE on `public` | §21.1 (D-3) | DB + CI introspection | `test_definer_functions_have_safe_search_path`, `test_public_has_no_temp_or_create_privilege` | P01 | — |
| INV-PLT-19 | Data migrations run as `qualloop_app` per tenant with the tenant GUC set and assert per-tenant row counts | §24.1.1 (D-7) | migration helper + CI | `test_data_migrations_set_tenant_guc_and_assert_counts` | P01 | I-01 |
| INV-PLT-20 | Jobs that exhaust 5 retries are recorded durably in Postgres (`job_dead_letters`, A-89) and alerted | §22.2 (m13) | WRK middleware + DB | `test_dead_lettered_job_recorded_in_job_dead_letters` | P01 | I-10 |
| INV-PLT-21 | All views are `security_invoker = true` (RLS applies to the caller) | §24.1.1 | DB + CI introspection | `test_all_views_are_security_invoker` | P01 | I-01 |
| INV-PLT-22 | One supplier actor value `supplier_session` in `app.actor_type` and `activity_log.actor_type` | §6.1 (m3) | DB CHECK + CMD | `test_supplier_actor_type_value_consistent` | P01/P05 | — |
| INV-PLT-23 | Document numbers use numeric max of `split_part(...)::int` per scope; unique; correct past 999 | §6 Numbering (m4) | CMD + DB unique | `test_numbering_past_999_uses_numeric_max`, `test_concurrent_numbering_no_duplicates` | P04 | — |

## 2. Masters & imports (§6.2, §6.7, §8 C2–C3)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-MST-01 | `customer_parts` is many-to-many; `parts` has no customer_id | §6.2 | DB schema | `test_part_can_link_to_many_customers` | P02 | — |
| INV-MST-02 | Supplier status values limited to five; change only by `change-status` with reason + `can_approve`; before/after logged | §6.2, §7.5, §15.6 | DB CHECK + CMD | `test_change_status_without_reason_rejected`, `test_change_status_without_can_approve_rejected`, `test_change_status_logs_before_after` | P02 | I-06 |
| INV-MST-03 | `status*` columns written only by the status command | §7.5 | CMD + CI | `test_supplier_update_command_ignores_status_fields` | P02 | I-06 |
| INV-MST-04 | Replace contact: old contact's links and sessions revoked, open SCARs reassigned (new link to new contact) | §8 C2 | CMD (in-transaction hook) | `test_replace_contact_revokes_links_and_sessions`, `test_replace_contact_reassigns_open_scars` | P02 (hook), P05 (links) | I-56 |
| INV-MST-05 | Disable contact requires reason; revokes links/sessions | §8 C2, §9 C7 | CMD + DB CHECK | `test_disable_contact_requires_reason`, `test_disable_contact_revokes_links_and_sessions` | P02/P05 | I-53 |
| INV-MST-06 | Contact unverified for 180 days must re-verify by OTP before new links are sent | §8 C2 | CMD (link issue) | `test_link_not_sent_to_contact_unverified_for_180_days` | P05 | I-55 |
| INV-IMP-01 | Same file uploaded twice is flagged before processing (file hash) | §8 C3 | CMD | `test_same_file_hash_flagged_before_processing` | P02 | I-35 |
| INV-IMP-02 | Natural keys + row hash: suppliers (GSTIN or name+city), parts (part_no), receipts (plant+GRN+part+lot), ERP rejections (plant+GRN+part+lot+ERP ref or row hash) | §8 C3 | CMD + DB unique | `test_duplicate_supplier_by_gstin_reported_not_merged`, `test_duplicate_supplier_by_name_and_city_reported_not_merged`, `test_duplicate_part_by_part_no_reported`, `test_erp_rejection_duplicate_by_reference_or_row_hash` | P02/P04 | I-35 |
| INV-IMP-03 | Importing the same 5,000-row receipt file twice creates zero duplicate receipts/defect events and reports 5,000 duplicates | §8 C3 | CMD + DB (`grn_receipts_natural_uq`, partial unique on `defect_events.source_ref`) | `test_same_5000_row_receipt_file_twice_creates_zero_duplicates`, `test_receipt_import_twice_creates_no_duplicate_defect_events` | P02/P04 | I-35 |
| INV-IMP-04 | Duplicates are reported, never silently merged or updated | §8 C3 | CMD | `test_changed_row_with_same_natural_key_goes_to_review_not_update` (A-41) | P02 | I-35 |
| INV-IMP-05 | Every batch report: received / valid / imported / duplicate / rejected / unmapped / needs review, reason per row, downloadable Excel | §8 C3 | CMD + WRK | `test_import_report_counts_reconcile_to_rows_received`, `test_import_report_has_reason_per_non_imported_row` | P02 | I-35 |
| INV-IMP-06 | Partial imports require explicit confirmation | §8 C3 | CMD | `test_partial_import_requires_explicit_confirmation` | P02 | I-35 |
| INV-IMP-07 | ERP rejection rows become unattributed `defect_events` (source erp_import), never a column added to NCR qty | §8 C3, §8 C4 | CMD | `test_erp_rejection_rows_create_unattributed_defect_events` | P04 | I-31 |
| INV-IMP-08 | CSV/Excel formula injection neutralised in exports | §21.1 (PHASES P02) | CMD (export writer) | `test_export_neutralises_formula_injection` | P02 | — |

## 3. Rejected quantity & attribution (§6.3, §11)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-QTY-01 | Every rejected unit = exactly one active defect event; metrics never add NCR qty to ERP qty and never take max | §11.1 | QRY (`v_receipt_rejections`) | `test_metrics_never_add_ncr_and_erp_quantities`, property test `test_prop_canonical_qty_never_exceeds_sum_of_active_events` | P04 | I-20 |
| INV-QTY-02 | `qty_rejected`, supplier, part, plant, source, source_ref, detected_at of a defect event are immutable | §11 (single source) | DB trigger | `test_defect_event_qty_update_rejected_db` | P04 | I-20 |
| INV-QTY-03 | Attribution status never returns to `unattributed` | §11.3 | DB trigger | `test_defect_event_cannot_return_to_unattributed_db` | P04 | — |
| INV-QTY-04 | Every attribution decision writes an append-only `defect_event_attributions` row; never edited, only superseded by a new decision | §6.3, §11.3 | DB (deferred trigger, grants, append-only) + CMD | `test_attribution_change_without_attribution_row_rejected_db`, `test_attribution_row_update_rejected_db`, `test_redecision_creates_new_row_latest_wins` | P04 | I-23 |
| INV-QTY-05 | NCR `qty_rejected` = Σ attributed defect events of the NCR (derived, not stored) | §6.3 | QRY (`v_ncr_quantities`) | `test_ncr_qty_rejected_equals_sum_of_attributed_events` | P04 | I-21 |
| INV-QTY-06 | Sources: NCR capture → attributed event per defect, linked to NCR (+receipt); ERP import → unattributed, no code; manual → attributed with code | §11.2, §8 C5 | CMD + DB CHECK | `test_ncr_capture_creates_one_attributed_event_per_defect`, `test_manual_rejection_creates_attributed_event_with_code`, `test_unattributed_event_must_be_erp_import_db` | P04 | I-22 |
| INV-QTY-07 | Four decisions and their effects: same (ERP superseded by NCR event), same-qty-corrected (one superseded; erp/ncr/accepted/difference + reason stored), different defect (ERP gets code, both count), internal (ERP superseded, excluded) | §11.3 | CMD + DB CHECK | `test_attribute_same_rejection_supersedes_erp_event`, `test_attribute_same_rejection_qty_corrected_stores_quantities_and_reason`, `test_attribute_different_defect_counts_both`, `test_attribute_internal_excludes_from_supplier_metrics` | P04 | I-24 |
| INV-QTY-08 | Receipts unique on (tenant, plant, grn_no, part_id, lot_no), NULL lot included | §6.3 | DB unique NULLS NOT DISTINCT | `test_duplicate_receipt_natural_key_rejected_db`, `test_duplicate_receipt_with_null_lot_rejected_db` | P04 | I-30 |
| INV-QTY-09 | Event receipt matches its supplier/part/plant; event category equals its code's category | §6.3 | DB trigger | `test_defect_event_receipt_mismatch_rejected_db` | P04 | — |
| INV-QTY-10 | System never attributes on its own; it suggests "same rejection" when receipt and qty match; user confirms | §11.3 | CMD (no system actor allowed on attribute) | `test_attribution_suggested_when_receipt_and_qty_match`, `test_system_actor_cannot_attribute` | P04 | I-25 |
| INV-QTY-11 | Canonical vs unreconciled per receipt per §11.4 (overlap → canonical = attributed, unreconciled = unattributed; else sum, unreconciled 0) | §11.4 | QRY | `test_canonical_qty_overlap_uses_attributed_only`, `test_canonical_qty_without_overlap_sums_both`, `test_receipt_with_only_unattributed_erp_counts_in_canonical` | P04 | I-26 |
| INV-QTY-12 | PPM labelled Provisional when unreconciled qty > 0 in period; label disappears after attribution | §11.4 | QRY | `test_ppm_provisional_when_unreconciled_qty`, `test_provisional_label_cleared_after_attribution` | P04/P07 | I-27 |
| INV-QTY-13 | Unattributed events never count toward repeats, signatures, effectiveness | §11.4 | QRY/WRK | `test_unattributed_event_ignored_by_repeat_signature_and_effectiveness` | P04/P06 | I-28 |
| INV-QTY-14 | Defect events without receipt are excluded from PPM until matched; matching suggested by supplier + part + lot | §11.4 | QRY + CMD (`link-receipt`, A-24) | `test_receiptless_event_excluded_from_ppm`, `test_receiptless_event_match_suggested_by_supplier_part_lot` | P04 | I-29 |
| INV-QTY-15 | Unreconciled qty is shown beside PPM, never added; labelled "awaiting reconciliation" | §12 | QRY + UI | `test_unreconciled_qty_not_added_to_ppm`, e2e `kpi tile shows awaiting reconciliation label` | P07/P08 | I-26 |
| INV-QTY-16 | As-of state of ERP, NCR and replacement events is reconstructable via `defect_event_state_as_of(cutoff)`; any event status/code/NCR change has an attribution row (trigger) | §11.1, §14.5 (M2) | DB trigger + QRY | `test_as_of_qty_corrected_counts_once`, `test_as_of_attribution_after_cutoff_ignored`, `test_ncr_event_status_change_without_attribution_rejected_db` | P04/P07 | I-20, I-89 |

## 4. NCR (§7.1, §8 C5, §9 C6)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-NCR-01 | Allowed transitions only: OPEN→CONTAINED→(AWAITING_SCAR│MONITOR│LOCAL_CLOSE); AWAITING_SCAR→LINKED_TO_SCAR→VERIFICATION→CLOSED; MONITOR→CLOSED; LOCAL_CLOSE→CLOSED; any open→CANCELLED | §7.1 | CMD (state table) | `test_ncr_allowed_transitions` (parametrised), `test_ncr_forbidden_transitions_rejected` (parametrised) | P04/P05 | — |
| INV-NCR-02 | MONITOR→CLOSED and LOCAL_CLOSE→CLOSED record a reason | §7.1 | CMD | `test_ncr_close_from_monitor_requires_reason`, `test_ncr_close_from_local_close_requires_reason` | P04 | — |
| INV-NCR-03 | Cancel requires reason and Admin or `can_approve` | §7.1 | CMD + DB CHECK | `test_ncr_cancel_requires_reason`, `test_ncr_cancel_requires_admin_or_can_approve` | P04 | I-41 |
| INV-NCR-04 | Cancelled NCR is frozen | §7.5 | DB trigger | `test_cancelled_ncr_update_rejected_db` | P04 | I-04 |
| INV-NCR-05 | Closed NCR immutable; correction only via `reopen` with reason | §7.5 | DB trigger + CMD | `test_closed_ncr_update_rejected_db`, `test_ncr_reopen_requires_reason` | P04 | I-05 |
| INV-NCR-06 | Disposition only via `dispose` command; changes logged before/after with reason | §7.5 | CMD | `test_dispose_logs_before_after`, `test_disposition_change_requires_reason` | P04 | I-06 |
| INV-NCR-07 | Use-as-is requires `can_approve` | §2.2, §8 C5 | CMD + DB trigger | `test_use_as_is_without_can_approve_rejected_api`, `test_use_as_is_without_can_approve_rejected_db` | P04 | I-40 |
| INV-NCR-08 | `capture_started_at` and `capture_submitted_at` stored for every captured NCR | §8 C5 | CMD | `test_ncr_capture_stores_capture_timestamps` | P04 | — |
| INV-NCR-09 | Defect signature = supplier + part + defect code (fallback category); repeat = same signature within 90 days | §8 C5 | CMD (signature service) | `test_repeat_flag_uses_signature_not_supplier_part_only`, `test_repeat_flag_category_fallback`, `test_repeat_flag_outside_90_days_false` | P04 | I-42 |
| INV-NCR-10 | Decision gate recommends SCAR required / Monitor / Local close / Add to existing SCAR; SQE decides; choice + reason logged | §9 C6 | CMD | `test_decision_gate_recommendation_matrix`, `test_decide_scar_logs_choice_and_reason` | P05 | — |
| INV-NCR-11 | Severity policy: critical → SCAR mandatory; major → required unless waived with reason; minor → optional, required on repeat (A-20) | §9 C6 | CMD | `test_critical_ncr_cannot_be_decided_without_scar`, `test_major_ncr_waiver_requires_reason`, `test_minor_ncr_repeat_requires_scar` | P05 | I-43 |
| INV-NCR-12 | Same-receipt unattributed ERP event is offered at capture ("same" / "different") | §8 C5 | CMD/QRY | `test_capture_offers_attribution_for_same_receipt_erp_event` | P04 | — |
| INV-NCR-13 | New NCR with same signature as an open SCAR is suggested for linking | §9 C6 | QRY | `test_new_ncr_with_open_scar_signature_suggested_for_link` | P05 | — |
| INV-NCR-14 | NCR appears on the SQE's My Work immediately after capture | §8 C5 | QRY | `test_new_ncr_visible_in_my_work_same_request_cycle` | P04/P08 | — |

## 5. SCAR (§6.3, §7.2, §9 C6–C7)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-SCR-01 | Allowed transitions only (§7.2 diagram incl. SENT_BACK → RESPONSE_STARTED revision+1, EFFECTIVENESS → REOPENED → RESPONSE_STARTED, EFFECTIVENESS → EFFECTIVENESS extend, DRAFT/ISSUED → CANCELLED) | §7.2 | CMD | `test_scar_allowed_transitions`, `test_scar_forbidden_transitions_rejected` | P05/P06 | — |
| INV-SCR-02 | SCAR cancel requires reason; only from DRAFT/ISSUED | §7.2 | CMD | `test_scar_cancel_requires_reason`, `test_scar_cancel_after_response_started_rejected` | P05 | — |
| INV-SCR-03 | One SCAR links many NCRs; all of the same supplier (and plant, A-28); exactly one primary | §6.3, §9 C6 | DB trigger + partial unique + CMD | `test_scar_links_many_ncrs`, `test_link_ncr_of_other_supplier_rejected_db`, `test_second_primary_link_rejected_db` | P05 | — |
| INV-SCR-04 | Due dates in calendar hours in plant timezone from `issued_at`: critical 24 h / 7 d, major 48 h / 10 d, minor — / 15 d | §9 C6 | CMD | `test_due_dates_by_severity_in_calendar_hours_plant_tz` | P05 | I-44 |
| INV-SCR-05 | `first_response_at` = first supplier action; `final_response_at` = first complete D3–D7 submission, never moved by later revisions; both write-once; response times only from explicit timestamps, never `updated_at` | §6.3, §9 C6 | DB trigger + CMD + QRY | `test_final_response_at_not_moved_by_later_revision`, `test_first_response_at_write_once_db`, `test_response_time_metrics_ignore_updated_at` | P05 | I-44, I-45 |
| INV-SCR-06 | Cancelled SCAR frozen; closed SCAR immutable except `reopen` with reason | §7.5 | DB trigger + CMD | `test_closed_scar_update_rejected_db`, `test_scar_reopen_requires_reason_and_can_approve` | P05 | I-05 |
| INV-SCR-07 | D4 requires occurrence, escape and systemic cause (plus D3, cause category, D5/D6, D7) to submit | §9 C7 | DB CHECK + CMD | `test_submit_without_escape_cause_rejected_api`, `test_submitted_response_missing_cause_rejected_db` | P05 | I-46 |
| INV-SCR-08 | Every revision kept; submitted revision immutable; drafts autosave; evidence attached only to open revision | §7.5, §9 C7 | DB trigger + CMD | `test_submitted_revision_update_rejected_db`, `test_send_back_creates_new_revision_all_retained`, `test_draft_autosave_updates_draft_only` | P05 | I-08, I-47 |
| INV-SCR-09 | Send-back requires a comment; triggers new notification | §9 C7 | DB CHECK + CMD | `test_send_back_without_comment_rejected`, `test_send_back_emits_SCAR_SENT_BACK` | P05 | I-47 |
| INV-SCR-10 | Reminders: day before due, on due, every 2 days overdue; escalation to Head of Quality at 3 days overdue (critical 1 day) | §9 C7 | WRK (scheduler) | `test_scar_reminder_schedule`, `test_scar_escalation_after_3_days_overdue`, `test_critical_scar_escalation_after_1_day` | P05 | — |
| INV-SCR-11 | AI 8D review assist never changes SCAR state | §20.1, §20.3 | CI + WRK | `test_ai_suggestion_never_changes_scar_state` | P05 | I-11 |
| INV-SCR-12 | SCAR closed/cancelled → its magic links revoked | §9 C7 | CMD | `test_scar_close_revokes_links`, `test_scar_cancel_revokes_links` | P05 | I-53 |

## 6. Supplier access (§9 C7, §21.2)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-SUP-01 | Token = 32 random bytes; only SHA-256 hash stored | §9 C7 | DB (bytea 32) + CMD | `test_magic_link_stores_only_token_hash`, `test_magic_link_token_has_32_bytes_entropy` | P05 | I-50 |
| INV-SUP-02 | OTP to the contact's verified mobile (or email) before any session | §9 C7 | CMD | `test_session_not_created_without_otp`, `test_otp_sent_to_contact_channel_only` | P05 | I-51 |
| INV-SUP-03 | Session scoped to ONE object + contact, valid 7 days; link re-openable for 30 days with new OTP | §9 C7 | DB trigger/CHECK + CMD | `test_session_scope_equals_link_scope_db`, `test_session_expires_after_7_days`, `test_link_reopen_within_30_days_requires_new_otp`, `test_link_after_30_days_fails` | P05 | I-52 |
| INV-SUP-04 | Expired, revoked and used-up links fail (generic error) | §21.2 | CMD | `test_expired_link_fails`, `test_revoked_link_fails`, `test_used_up_link_fails` (A-36) | P05 | I-53 |
| INV-SUP-05 | Disabled/replaced contact's sessions fail | §21.2 | CMD (session resolver checks contact active) | `test_disabled_contact_session_fails`, `test_replaced_contact_session_fails` | P05 | I-53 |
| INV-SUP-06 | Supplier session cannot access any object other than its own | §21.2 | CMD (no object ids in supplier routes) + DB | `test_supplier_session_cannot_read_other_scar`, `test_supplier_session_cannot_read_other_supplier`, `test_supplier_session_cannot_read_other_ncr` | P05 | I-54 |
| INV-SUP-07 | Supplier never sees internal risk, score, costs, debit amounts, internal comments, other NCRs/SCARs | §9 C7, §21.2 | SCH (allow-list) + DB (`p_supplier_deny` default deny, scoped RLS) | `test_supplier_scar_view_schema_has_no_internal_fields`, `test_supplier_actor_cannot_select_cost_tables_db`, `test_supplier_session_cannot_see_internal_costs_risk_comments` | P05 | I-54 |
| INV-SUP-08 | OTP verification is rate limited; repeated failures revoke the link (A-78) | §21.1, §21.2 | CMD (Redis counters) | `test_otp_rate_limited`, `test_link_revoked_after_failed_otp_limit` | P05 | — |
| INV-SUP-09 | Supplier actor is denied on every table by default (`p_supplier_deny`); only the DATA_MODEL.md §0.5 list opts in | §21.2 (D-1/B1) | DB + CI introspection | `test_every_rls_table_has_supplier_policy`, `test_supplier_rls_denies_unlisted_tables_db` | P01/P05 | I-54 |
| INV-SUP-10 | Scoped supplier predicates: SCAR scope sees only its SCAR, links, linked NCRs/photos/attributed events/codes/parts, own responses/evidence, send-back reviews, own messages; document scope only its supplier's requested requirements and supplier-uploaded documents; `activity_log`/`outbox_events` insert-only; never DELETE | §9 C7, §21.2 (D-2) | DB | `test_supplier_rls_scar_scope_db`, `test_supplier_rls_document_upload_scope_db`, `test_supplier_cannot_select_activity_log_or_outbox_db`, `test_supplier_cannot_delete_any_row_db` | P05 | I-54 |
| INV-SUP-11 | Magic-link token leaves the URL on first request (exchange → HttpOnly `ql_pre` → 303 `/s`); `/s/*` and the token never logged; raw tokens rejected in `/supplier-access/{token}/*` paths | §9 C7, §21.1 (D-4) | web route + CMD + logging config | `test_link_open_exchanges_token_for_cookie_and_redirects`, `test_access_log_redacts_magic_link_token`, `test_verify_otp_rejects_raw_token_in_path` | P05 | I-50 |
| INV-SUP-12 | OTP failures persisted in `magic_links.otp_failed_count` (A-86); per-IP limits on request-otp and verify-otp | §21.1 (D-6) | CMD + DB | `test_otp_failure_count_persisted_in_db`, `test_otp_per_ip_limit` | P05 | — |
| INV-SUP-13 | Magic link created in the send job in the same transaction as its `messages` row (`magic_link_id`, A-87); plaintext token never persisted; lost/retried send re-issues and revokes the old link | §9 C7, §22.2 (M3) | WRK + DB | `test_magic_link_created_in_send_job_with_message`, `test_lost_send_reissues_link_and_revokes_old`, `test_plaintext_token_never_persisted` | P05 | I-50 |

## 7. Effectiveness (§6.3, §9 C8)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-EFF-01 | Starts when SCAR accepted; stores signature of linked NCRs (codes/categories + characteristic) | §9 C8 | WRK (on SCAR_ACCEPTED) | `test_effectiveness_check_created_on_accept_with_signature` | P06 | I-48 |
| INV-EFF-02 | Criteria: min lots AND min days (+ optional min qty) per severity | §9 C6, §9 C8 | WRK | `test_effectiveness_requires_lots_and_days`, `test_effectiveness_min_qty_optional` | P06 | I-48 |
| INV-EFF-03 | Pass only when criteria met with no signature match; fail only on an attributed matching event → SCAR REOPENED, event stored, supplier notified, EFFECTIVENESS_FAIL | §9 C8 | WRK + DB CHECK | `test_effectiveness_passes_when_criteria_met_without_match`, `test_effectiveness_fails_on_matching_attributed_event_and_reopens_scar` | P06 | I-48 |
| INV-EFF-04 | Different defect on same part does not fail | §9 C8 | WRK | `test_effectiveness_unrelated_defect_same_part_not_failed` | P06 | I-48 |
| INV-EFF-05 | Unattributed ERP rejection on a watched receipt holds (not passed) until attributed | §9 C8 | WRK | `test_effectiveness_held_while_unattributed_erp_on_watched_receipt` | P06 | I-48 |
| INV-EFF-06 | After 90 days pending → My Work; Extend (reason, extensions+1, max 2) or Close–no data (reason) | §9 C8 | CMD + DB CHECK | `test_effectiveness_pending_90_days_appears_in_my_work`, `test_effectiveness_third_extend_rejected_api`, `test_effectiveness_extensions_above_2_rejected_db`, `test_close_no_data_requires_reason` | P06 | I-49 |
| INV-EFF-07 | Never passed or failed without data; closed_no_data counted separately, shown "not verified" | §9 C8 | WRK + DB CHECK + QRY | `test_effectiveness_not_passed_without_receipts`, `test_closed_no_data_counted_separately_from_passed` | P06 | I-49 |
| INV-EFF-08 | SCAR close after effectiveness is driven by `effectiveness` (all checks passed, or close-no-data) in the same transaction; linked NCRs close and links are revoked | §9 C8, §7.2 (M4) | WRK/CMD | `test_all_checks_passed_closes_scar_and_ncrs`, `test_close_no_data_closes_scar_and_revokes_links` | P06 | — |

## 8. Money (§6.3, §10)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-MON-01 | Debit note cannot be saved until Σ allocations = debit note amount | §6.3, §10 | CMD + DB (deferred constraint trigger) | `test_debit_note_not_fully_allocated_rejected_api`, `test_debit_note_not_fully_allocated_rejected_db` | P06 | I-60 |
| INV-MON-02 | Allocations only to cost lines with `recoverable = true`; recoverable cannot be unset while allocated | §6.3, §10 | CMD + DB trigger | `test_allocation_to_non_recoverable_cost_line_rejected_api`, `test_allocation_to_non_recoverable_cost_line_rejected_db`, `test_unset_recoverable_with_allocations_rejected_db` | P06 | I-61 |
| INV-MON-03 | Σ allocations per cost line ≤ cost line amount | §6.3 | CMD + DB trigger (row lock) | `test_cost_line_overallocation_rejected_api`, `test_cost_line_overallocation_rejected_db` | P06 | I-62 |
| INV-MON-04 | Per allocation: recovered + written_off ≤ allocation amount (application command AND DB constraint trigger) | §6.3, §10 | CMD + DB trigger (row lock) | `test_recovery_plus_writeoff_cannot_exceed_allocation_api`, `test_recovery_plus_writeoff_cannot_exceed_allocation_db`, `test_two_concurrent_recoveries_cannot_breach_allocation` | P06 | I-63 |
| INV-MON-05 | Outstanding never negative | §10 | follows from INV-MON-04; QRY | property `test_prop_outstanding_never_negative` | P06 | I-64 |
| INV-MON-06 | Recovery fully allocated; auto pro-rata to remaining outstanding, never above; rounding remainder to largest outstanding (tie → lowest id, A-39); manual override within the same limit | §6.3 | CMD + DB deferred trigger | `test_recovery_pro_rata_to_remaining_outstanding`, `test_recovery_rounding_remainder_to_largest_outstanding`, `test_manual_recovery_override_within_limit`, `test_recovery_not_fully_allocated_rejected_db`, property `test_prop_recovery_allocation_sums_to_recovery` | P06 | I-65 |
| INV-MON-07 | Changing an allocation after recovery requires a command with reason | §10 | CMD | `test_change_allocation_after_recovery_requires_reason` | P06 | I-66 |
| INV-MON-08 | Recoveries, recovery allocations, write-offs are append-only (A-79) | §7.5 | DB grants + trigger | `test_recovery_update_rejected_db`, `test_write_off_delete_rejected_db` | P06 | — |
| INV-MON-09 | Write-off per allocation with reason + approver (`can_approve`, A-79) | §10 | CMD + DB CHECK/trigger | `test_write_off_requires_reason`, `test_write_off_approver_must_have_can_approve_db` | P06 | — |
| INV-MON-10 | Allocated cost lines belong to NCRs of the debit note's supplier (A-69) | §10 (traceability) | CMD + DB trigger | `test_allocation_to_other_supplier_cost_line_rejected_db` | P06 | — |
| INV-MON-11 | Per cost line: debited, recovered, written_off, undebited (recoverable only), outstanding, net_exposure per §10 formulas | §10 | QRY (`v_cost_line_balances`) | `test_cost_line_balance_formulas` | P06 | — |
| INV-MON-12 | Exposure cohort (incurred_on in period; Recovery % = recovered to date ÷ gross exposure) and cash view (recovered_on in period, by exposure month, no %) never mixed | §10 | QRY | `test_exposure_cohort_view_definitions`, `test_cash_view_has_no_percentage` | P06 | I-67 |
| INV-MON-13 | Money is entered by people; AI never calculates or edits money; money stored as BIGINT paise | §10, §20.1, CLAUDE.md §6 | CI (import-linter: `ai` cannot import `finance`) + DB types | `test_ai_module_cannot_import_finance`, `test_all_money_columns_are_bigint_paise` | P06 | I-68, I-69 |
| INV-MON-14 | Debit note creation is idempotent by request ID | §22.2 | CMD + DB (`idempotency_keys`) | `test_debit_note_create_same_idempotency_key_creates_once` | P06 | — |
| INV-MON-15 | Money commands and triggers run at READ COMMITTED, lock before summing (separate statement), fixed lock order debit_note → allocations by id → cost lines by id | §10 (M1) | CMD + DB trigger | `test_money_commands_lock_in_fixed_order_no_deadlock`, `test_concurrent_allocation_and_recovery_no_deadlock` | P06 | I-63 |

## 9. Documents & certificates (§6.4, §7.3, §7.4, §8 C10, §13, §20.2)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-DOC-01 | Validity never stored; computed per read from `expiry_date` and today in plant timezone; only APPROVED certificates have validity; buckets per §7.3 table | §6.4, §7.3 | QRY (`certificate_validity`) + DB (no column) | `test_certificate_validity_buckets`, `test_only_approved_certificates_have_validity`, `test_no_validity_column_exists` | P03 | I-70 |
| INV-DOC-02 | Certificate status transitions only PENDING_REVIEW → APPROVED/REJECTED, APPROVED → SUPERSEDED (newer approved) | §7.3 | CMD + DB trigger | `test_certificate_status_transitions_db`, `test_approving_newer_certificate_supersedes_previous` | P03 | — |
| INV-DOC-03 | Requirement status machine (first-time vs renewal paths); APPROVED stays APPROVED during renewal | §7.4 | CMD | `test_requirement_first_time_path`, `test_requirement_stays_approved_during_renewal`, `test_rejected_first_time_upload_returns_to_requested_with_new_due_at` | P03 | I-74 |
| INV-DOC-04 | Compliance computed from current certificate + validity + active exception; never from `status = approved` alone | §7.4 | QRY | `test_compliance_not_derived_from_status_alone`, `test_expired_current_certificate_is_non_compliant_despite_approved_status` | P03 | I-71 |
| INV-DOC-05 | `current_certificate_id` references an approved certificate of the same supplier and doc type | §7.4 | DB trigger | `test_current_certificate_must_be_approved_same_supplier_db` | P03 | — |
| INV-DOC-06 | One `supplier_requirements` row per supplier per mandatory doc type, created `not_requested` on supplier create / category change | §6.4, §8 C10 | CMD (in-transaction hook) + DB unique | `test_supplier_create_creates_not_requested_requirements`, `test_category_change_adds_new_mandatory_requirements` | P03 | I-73 |
| INV-DOC-07 | Requirements `not_requested` after 7 days appear on My Work; bulk "request all missing" sets `due_at = requested_at + grace_days` | §8 C10 | QRY + CMD | `test_not_requested_after_7_days_on_my_work`, `test_request_documents_sets_due_at_from_grace_days` | P03/P08 | — |
| INV-DOC-08 | Exception computed (`valid_until ≥ today`), max 90 days, `can_approve`; suppresses CERT_EXPIRED/CERT_MISSING, not reminders; lapses automatically | §7.4, §13 | QRY + CMD + DB trigger | `test_exception_active_until_valid_until`, `test_exception_over_90_days_rejected`, `test_exception_suppresses_cert_risk_not_reminders`, `test_exception_lapses_without_job` | P03 (logic) / P10 (UI) | I-72 |
| INV-DOC-09 | Expiry escalation: 60 d auto-request, 30 d reminder + SQE task, 7 d reminder + HoQ escalation, expired daily 7 days then weekly | §8 C10 | WRK (daily scan) | `test_expiry_escalation_schedule` | P05 | — |
| INV-DOC-10 | Upload PDF/JPG/PNG ≤ 20 MB, content-type (magic bytes) check + virus scan before use | §20.2, §21.1 | CMD + WRK | `test_upload_rejects_wrong_content_type`, `test_upload_rejects_over_20_mb`, `test_unscanned_file_not_downloadable` | P01/P03 | I-76 |
| INV-DOC-11 | AI extraction stores model, model version, prompt version, extraction version, source hash, spans, latency, cost, reviewer corrections | §20.2 | WRK + DB NOT NULL | `test_ai_extraction_persists_reproducibility_fields` | P03 | I-77 |
| INV-DOC-12 | AI never sets certificate status; AI outage → manual entry works | §20.1 | CI + CMD | `test_ai_never_sets_certificate_status`, `test_certificate_manual_entry_works_when_ai_unavailable` | P03 | I-11, I-12 |
| INV-DOC-13 | Daily scan emits CERTIFICATE_VALIDITY_CHANGED / REQUIREMENT_OVERDUE only when computed state ≠ last successfully sent message state (sent/delivered/read, `variables.state`) | §22.3 | WRK | `test_daily_scan_emits_when_state_differs_from_last_sent`, `test_daily_scan_ignores_failed_messages_as_last_state` | P05 | I-75 |
| INV-DOC-14 | Rejected replacement (renewal) upload: `current_certificate_id` unchanged, `renewal_due_at` reset (new value per SPEC-GAP A-45), supplier asked again; still compliant while current valid, non-compliant (computed) once it has expired | §7.4 | CMD + QRY | `test_rejected_renewal_resets_renewal_due_at_and_rerequests`, `test_rejected_renewal_after_current_expired_is_non_compliant` | P03 | I-74 |

## 10. Metrics (§12)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-MET-01 | Every metric is per supplier (and supplier-part where shown), per plant, for an explicit period | §12 | QRY (signature requires period) | `test_metric_api_requires_explicit_period` | P07 | I-80 |
| INV-MET-02 | PPM = Σ canonical ÷ Σ qty_received × 1,000,000 over receipts with grn_date in period | §12 | QRY | `test_ppm_formula_fixture` | P07 | I-81 |
| INV-MET-03 | Quantity rejection % and lot rejection rate per §12 | §12 | QRY | `test_qty_rejection_pct_fixture`, `test_lot_rejection_rate_fixture` | P07 | I-81 |
| INV-MET-04 | PPM by defect uses attributed events with the code/category only | §12 | QRY | `test_ppm_by_defect_uses_attributed_events_only` | P07 | I-81 |
| INV-MET-05 | Repeat NCRs, customer disruptions, premium freight occurrences counts in period | §12 | QRY | `test_repeat_ncr_count_fixture`, `test_customer_disruption_count_fixture`, `test_premium_freight_occurrences_fixture` | P07 | I-81 |
| INV-MET-06 | SCAR due-status exactly one of on_time / late / overdue; not-yet-due and cancelled excluded; open overdue stays in denominator; evaluated as of period end | §12 | QRY (`scar_due_status`) | `test_scar_due_status_single_value`, `test_scar_on_time_pct_excludes_not_yet_due_and_cancelled` | P07 | I-82 |
| INV-MET-07 | Late completions reported in the later month, never changing the earlier | §12 | QRY | `test_late_completion_reported_in_submission_month` | P07 | I-82 |
| INV-MET-08 | Time to first response = median(first_response_at − issued_at); time to acceptance = median(accepted_at − issued_at) | §12 | QRY | `test_time_to_first_response_median`, `test_time_to_acceptance_median` | P07 | I-81 |
| INV-MET-09 | Document compliance % = compliant ÷ due; not_requested and not-yet-due excluded and shown as pending | §12 | QRY | `test_document_compliance_pct_with_pending_exclusion` | P03/P07 | I-81 |
| INV-MET-10 | NCR capture time median and p90 | §12 | QRY | `test_ncr_capture_time_median_and_p90` | P07 | I-81 |
| INV-MET-11 | Minimum sample: PPM/rejection ≥ 5 receipts AND ≥ 1,000 units; SCAR metrics ≥ 1 SCAR due; else "N/A — insufficient data" | §12.1 | QRY | `test_ppm_na_below_5_receipts`, `test_ppm_na_below_1000_units`, `test_scar_metric_na_without_due_scar` | P07 | I-83 |
| INV-MET-12 | Every metric returns value + sample + coverage + freshness + "how calculated" payload whose records sum to the value | §4.6–7, §12.1, §16 | QRY + SCH | `test_metric_payload_has_sample_coverage_freshness`, `test_metric_drilldown_records_sum_to_value` | P07/P08 | I-84 |
| INV-MET-13 | As-of rule: closed period uses only event timestamps ≤ period_end; later events appear in their own period | §14.5 | QRY (`*_as_of(cutoff)`) | `test_as_of_ignores_events_after_period_end` | P07 | I-89 |

## 11. Score (§14)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-SCO-01 | Weights 50/20/15/15 (tenant settings default) | §14.1 | QRY | `test_score_default_weights` | P07 | I-85 |
| INV-SCO-02 | Quality = 100 if PPM ≤ target, linear to 0 at 10× target | §14.1 | QRY | `test_quality_component_linear_between_target_and_10x` | P07 | I-85 |
| INV-SCO-03 | Responsiveness = SCAR on-time %; Documents = compliance %; Repeat = 100 − 25/repeat − 40/disruption, min 0 | §14.1 | QRY | `test_response_component_equals_on_time_pct`, `test_repeat_component_floor_zero`, `test_document_component_equals_compliance_pct` | P07 | I-85 |
| INV-SCO-04 | Component below minimum sample is N/A (never 100); total re-weighted over available components | §14.2 | QRY | `test_na_component_not_scored_as_100`, `test_total_reweighted_across_available_components` | P07 | I-85 |
| INV-SCO-05 | Quality N/A → no total and no grade ("Insufficient data") | §14.2 | QRY + DB CHECK | `test_no_total_or_grade_when_quality_na`, `test_snapshot_total_without_quality_rejected_db` | P07 | I-85 |
| INV-SCO-06 | Grades A ≥ 85, B 70–84, C 50–69, D < 50; never shown without components and coverage | §14.3 | QRY + DB CHECK + UI | `test_grade_bands`, e2e `score always rendered with components and coverage` | P07/P08 | I-86 |
| INV-SCO-07 | Insufficient-data suppliers never ranked above measured ones (listed separately) | §14.3, §16 | QRY | `test_ranking_lists_insufficient_data_separately` | P07 | I-87 |
| INV-SCO-08 | Monthly snapshot on the 1st with formula_version, period, inputs; immutable; weight/target changes affect future periods only | §14.5, §7.5 | WRK + DB (append-only, unique period) | `test_monthly_snapshot_written_on_first`, `test_snapshot_update_rejected_db`, `test_weight_change_does_not_alter_existing_snapshot`, `test_snapshot_job_rerun_is_idempotent` | P07 | I-07, I-88 |
| INV-SCO-09 | Targets: tenant default (demo 500) with supplier-part override | §14.4 | QRY | `test_supplier_part_target_overrides_tenant_default` | P07 | — |
| INV-SCO-10 | Historical data corrections do not change closed snapshots; listed as "Corrections to earlier periods" with before/after from activity log | §14.5 | QRY + reports | `test_march_correction_of_january_receipt_leaves_january_snapshot`, `test_corrections_to_earlier_periods_listed_with_before_after` | P07 | I-89 |
| INV-SCO-11 | Snapshots evaluate date-based functions (validity, compliance, exceptions) with `today = period_end`, never the run date | §14.5 (m1) | WRK | `test_snapshot_uses_period_end_as_today_for_validity` | P07 | I-89 |

## 12. Risk (§15)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-RSK-01 | Risk recalculated from active conditions nightly and on relevant events; not a running total; conditions age out | §15.1 | WRK | `test_risk_recalculated_from_active_conditions`, `test_condition_ages_out_of_window` | P07 | I-90 |
| INV-RSK-02 | Each rule fires with its condition, window, points and caps per §15.2 (11 rules) | §15.2 | WRK | `test_rule_CRITICAL_NCR_points_and_cap_35`, `test_rule_PPM_HIGH`, `test_rule_PPM_RISING`, `test_rule_SCAR_OVERDUE_points_and_cap_30`, `test_rule_REPEAT_DEFECT`, `test_rule_CUSTOMER_DISRUPTION`, `test_rule_EFFECTIVENESS_FAIL`, `test_rule_CERT_EXPIRED`, `test_rule_CERT_MISSING`, `test_rule_CERT_EXPIRING`, `test_rule_SUPPLIER_NO_RESPONSE` | P07 | I-91 |
| INV-RSK-03 | Total capped at 100; Low 0–29, Medium 30–59, High ≥ 60 | §15.2 | WRK + DB CHECK | `test_risk_total_capped_at_100`, `test_risk_level_bands`, `test_risk_level_inconsistent_with_score_rejected_db` | P07 | I-91 |
| INV-RSK-04 | Each active condition is a `risk_events` row; clearing sets active=false + cleared_at | §15.3 | WRK + DB CHECK | `test_cleared_condition_sets_inactive_and_cleared_at` | P07 | I-92 |
| INV-RSK-05 | Reason text generated from rule_code + params (reproducible) | §15.3 | QRY | `test_reason_text_reproducible_from_rule_code_and_params` | P07 | I-92 |
| INV-RSK-06 | Risk never changes supplier status; may suggest on_watch after two consecutive High months | §15.6 | CI (risk cannot import masters commands) + WRK | `test_risk_never_changes_supplier_status`, `test_on_watch_suggested_after_two_high_months` | P07 | I-94 |
| INV-RSK-07 | CERT_MISSING only when requirement `requested` and due_at passed; not for not_requested; suppressed by active exception | §15.2, §13 | WRK | covered by R4-12, R4-13, `test_cert_missing_suppressed_by_active_exception` | P07 | — |
| INV-RSK-08 | Override keeps system score underneath; both shown; reason + expiry; `can_approve` | §15.5 | QRY + DB | `test_override_keeps_system_score`, `test_override_requires_can_approve_db` | P10 | I-93 |

## 13. Notifications (§17, §22.2)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-NTF-01 | Application raises `notification_type`; no WhatsApp logic outside `notifications/` | §17.2 | CI (import-linter + grep) | `test_whatsapp_client_only_imported_in_notifications` | P05 | I-13 |
| INV-NTF-02 | Sends idempotent: unique idempotency_key; retries do not duplicate | §22.2 | DB unique + WRK | `test_retry_does_not_send_duplicate_message` | P05 | I-10 |
| INV-NTF-03 | Opt-out (STOP/UNSUBSCRIBE) switches contact to email; never blocks a workflow | §17.3 | WRK | `test_stop_reply_opts_out_and_switches_to_email`, `test_opted_out_contact_receives_email_only` | P05 | I-14 |
| INV-NTF-04 | Failed WhatsApp delivery triggers email/SMS fallback within 15 minutes | §17.4 | WRK | `test_whatsapp_failure_falls_back_to_email_within_15_minutes` | P05 | I-14 |
| INV-NTF-05 | Message status moves forward only; transitions, click and response stored | §17.4 | DB trigger + WRK | `test_message_status_cannot_move_backwards_db`, `test_message_click_and_response_recorded` | P05 | — |
| INV-NTF-06 | Every supplier flow works with email + web link alone | §4.10, §17.1 | E2E | e2e `supplier completes 8D via email link only` | P05 | I-14 |

## 14. Security (§21.1, §21.2)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-SEC-01 | Tenant A cannot read or write Tenant B suppliers, NCRs, SCARs, files (API + ORM + worker + signed URLs) | §21.2 | DB + CMD + storage key prefix check | `test_tenant_a_cannot_read_tenant_b_suppliers_api`, `test_tenant_a_cannot_read_tenant_b_ncrs_api`, `test_tenant_a_cannot_read_tenant_b_scars_api`, `test_tenant_a_cannot_get_signed_url_for_tenant_b_file` | P01–P05 | I-01 |
| INV-SEC-02 | Signed file URLs expire (≤ 15 min); unauthorised user cannot obtain them | §21.1, §21.2 | CMD | `test_signed_url_expires_within_15_minutes`, `test_unauthorised_user_cannot_get_signed_url` | P01 | I-76 |
| INV-SEC-03 | Viewer cannot export or download where not permitted (A-70) | §21.2 | CMD | `test_viewer_cannot_export_excel`, `test_viewer_cannot_download_documents` | P02/P08 | — |
| INV-SEC-04 | Passwords hashed with argon2id; login rate limited; secure session cookies | §21.1 | CMD | `test_password_stored_as_argon2id`, `test_login_rate_limited`, `test_session_cookie_flags_secure_httponly_samesite` | P01 | — |
| INV-SEC-05 | Excel export permission-checked and logged | §16 C14 | CMD | `test_export_writes_activity_log` | P02/P08 | — |
| INV-SEC-06 | Private buckets only | §21.1 | IaC + CI | `test_bucket_policy_blocks_public_access` (IaC policy test) | P09 | I-76 |
| INV-SEC-07 | Contact anonymisation retains quality records with placeholder | §21.5 | CMD | `test_contact_anonymisation_keeps_records_with_placeholder` | P05 | — |
| INV-SEC-08 | Redis requires AUTH with a least-privilege ACL user; admin/dangerous commands denied; reachable only from app tasks | §21.1 (D-5) | infra (compose ACL, IaC SG) | `test_redis_app_user_cannot_run_admin_commands` | P01/P09 | — |
| INV-SEC-09 | Personal data is not sent to processors outside India without recorded approval (e.g. error tracking) | §21.5 (D-8) | config review | `test_error_tracking_disabled_unless_approved_flag_set` | P09 | — |

## 15. AI (§20, §24.1.3)

| ID | Invariant | § | Enforcement | Test name(s) | Phase | I-xx |
| --- | --- | --- | --- | --- | --- | --- |
| INV-AI-01 | AI calls only from background jobs through `ai/providers/` | §24.1.3 | CI (import-linter: `ai.providers` importable only from `*.jobs`) | `test_ai_providers_imported_only_by_jobs` | P03 | I-11 |
| INV-AI-02 | AI never approves/rejects certificates, closes NCR/SCAR, changes supplier status, overrides risk, calculates/edits money, deletes records | §20.1 | CMD (AI actor type denied on all commands) | `test_ai_actor_denied_on_every_command` | P03 | I-11 |
| INV-AI-03 | Every workflow works with AI unavailable | §20.1 | E2E/integration | `test_document_review_works_with_ai_provider_down` | P03 | I-12 |
| INV-AI-04 | Benchmarks gate releases: certificates type ≥ 95%, expiry ≥ 92%, cert no ≥ 90%, no metric drop > 2 points; 8D no drop > 5 points | §20.5 | CI job on model/prompt change | `bench_certificates_meets_release_gate`, `bench_8d_review_no_regression` | P03/P09 | — |
| INV-AI-05 | 8D/document text treated as untrusted: schema-constrained output only, advisory, rendered escaped, cannot trigger commands | §20.1, §20.3 (D-8) | WRK + SCH + UI | `test_8d_assist_output_is_advisory_and_escaped` | P05 | I-11 |

---

## 16. §24.1 rule 4 fixture cases (each must exist with exactly this name)

| ID | Fixture case (§24.1.4) | Test name | Location | Phase |
| --- | --- | --- | --- | --- |
| R4-01 | Insufficient data | `test_r4_insufficient_data_returns_na` | `tests/unit/scoring/` | P07 |
| R4-02 | ERP + NCR for the same rejection (counted once) | `test_r4_erp_and_ncr_same_rejection_counted_once` | `tests/unit/receipts/` | P04 |
| R4-03 | ERP + NCR for different defects (both counted) | `test_r4_erp_and_ncr_different_defects_both_counted` | `tests/unit/receipts/` | P04 |
| R4-04 | Internal (non-supplier) rejection excluded | `test_r4_internal_rejection_excluded` | `tests/unit/receipts/` | P04 |
| R4-05 | One debit note across three NCRs with partial recovery and a write-off | `test_r4_one_debit_note_three_ncrs_partial_recovery_and_write_off` | `tests/integration/finance/` | P06 |
| R4-06 | Recovery recorded in a later month than the exposure (cohort vs cash view) | `test_r4_recovery_in_later_month_cohort_vs_cash` | `tests/integration/finance/` | P06 |
| R4-07 | Effectiveness with an unrelated defect on the same part (must not fail) | `test_r4_effectiveness_unrelated_defect_same_part_not_failed` | `tests/integration/effectiveness/` | P06 |
| R4-08 | Effectiveness with a matching defect (must fail) | `test_r4_effectiveness_matching_defect_fails` | `tests/integration/effectiveness/` | P06 |
| R4-09 | Allocation to a non-recoverable cost line (rejected) | `test_r4_allocation_to_non_recoverable_cost_line_rejected` | `tests/integration/finance/` | P06 |
| R4-10 | Recovery + write-off exceeding an allocation (rejected) | `test_r4_recovery_plus_write_off_exceeding_allocation_rejected` | `tests/integration/finance/` | P06 |
| R4-11 | Certificate validity changing across 60/30/7/0-day boundaries with no job run | `test_r4_certificate_validity_boundaries_60_30_7_0_without_job` | `tests/unit/documents/` | P03 |
| R4-12 | New supplier with requirements not yet requested (no CERT_MISSING) | `test_r4_new_supplier_not_requested_no_cert_missing` | `tests/unit/documents/` (condition fn, P03) + `tests/unit/risk/` (P07) | P03/P07 |
| R4-13 | Requirement past due (fires) | `test_r4_requirement_past_due_fires_cert_missing` | `tests/unit/documents/` + `tests/unit/risk/` | P03/P07 |
| R4-14 | Receipt with both NCR and unattributed ERP events (ERP qty excluded from PPM, PPM provisional) | `test_r4_receipt_with_ncr_and_unattributed_erp_excluded_and_provisional` | `tests/unit/receipts/` + `tests/unit/scoring/` | P04/P07 |
| R4-15 | SCAR on-time with on-time, late, overdue and not-yet-due SCARs | `test_r4_scar_on_time_with_on_time_late_overdue_not_yet_due` | `tests/unit/scoring/` | P07 |
| R4-16 | SCAR overdue at September month-end then submitted in October (September snapshot unchanged, October shows a late completion) | `test_r4_scar_overdue_september_submitted_october_snapshot_unchanged` | `tests/integration/scoring/` | P07 |
| R4-17 | Rejected renewal upload while the current certificate is valid (still compliant, current_certificate_id unchanged) | `test_r4_rejected_renewal_while_current_valid_still_compliant` | `tests/integration/documents/` | P03 |
| R4-18 | Rejected first-time upload (requirement missing after new due date) | `test_r4_rejected_first_time_upload_missing_after_new_due_date` | `tests/integration/documents/` | P03 |
| R4-19 | Daily scan run twice in a row (no duplicate notification) | `test_r4_daily_scan_twice_no_duplicate_notification` | `tests/integration/notifications/` | P05 |
| R4-20 | Daily scan skipped for a day (notification sent next run) | `test_r4_daily_scan_skipped_day_sends_next_run` | `tests/integration/notifications/` | P05 |
| R4-21 | Effectiveness extend twice then close-no-data | `test_r4_effectiveness_extend_twice_then_close_no_data` | `tests/integration/effectiveness/` | P06 |

## 17. §21.2 mandatory security tests (CI, `api/tests/security/`)

| §21.2 item | Test name(s) |
| --- | --- |
| Tenant A cannot read or write Tenant B suppliers, NCRs, SCARs, files | INV-SEC-01 tests + `test_tenant_a_cannot_write_tenant_b_supplier_api` |
| Supplier session cannot access any object other than its own | INV-SUP-06 tests |
| Supplier session cannot see internal costs, risk, comments | INV-SUP-07 tests |
| Expired, revoked and used-up links fail | INV-SUP-04 tests |
| Disabled contact's sessions fail | `test_disabled_contact_session_fails` |
| Signed file URLs expire | `test_signed_url_expires_within_15_minutes` |
| Viewer cannot export or download where not permitted | INV-SEC-03 tests |

## 18. Coverage check

| Source section | Invariant ids |
| --- | --- |
| §6 constraints | INV-PLT-01/07/09, INV-MST-01, INV-QTY-04/05/08, INV-SCR-03/05, INV-MON-01..04, INV-DOC-01/06, INV-SCO-08, INV-IMP-03 |
| §7 (7.1–7.5) | INV-PLT-04..08, INV-NCR-01..07, INV-SCR-01/02/06/08, INV-DOC-01..05, INV-MST-02, INV-SCO-08 |
| §9 C6 | INV-NCR-10/11/13, INV-SCR-03/04/05 |
| §9 C7 | INV-SCR-07..10/12, INV-SUP-01..08 |
| §9 C8 | INV-EFF-01..07 |
| §10 | INV-MON-01..14 |
| §11 | INV-QTY-01..15 |
| §12 | INV-MET-01..13, INV-QTY-12/15 |
| §14 | INV-SCO-01..10, INV-MET-13 |
| §15 | INV-RSK-01..08 |
| §21.2 | §17 table, INV-SUP-09..13 |
| §22.2 | INV-PLT-11..14, INV-NTF-02, INV-MON-14 |
| §22.3 | INV-PLT-15, INV-DOC-13, R4-19/20 |
| §24.1 | INV-PLT-01/04/16/17, INV-AI-01, R4-01..21 |
