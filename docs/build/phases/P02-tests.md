# P02 tests: spec rule to test map

Written from `PHASES.md` P02, `P02-plan.md`, blueprint 6.2, 6.7, 7.5, 8 C2, 8 C3, 15.6, 17.3, 21.1, 21.2 and the
architecture documents, before any P02 code exists. Interfaces the tests assume are in `P02-test-contract.md`. Test
names listed here are the names the verifier greps for. Paths are under `api/tests/` unless they start with `web/`.

Run: `make test-api`, `make test-web`, `make e2e` (stack up with `make up` and `make seed`; on this machine
`QL_PG_HOST_PORT=55432 QL_REDIS_HOST_PORT=56379`). The API suite needs `openpyxl` (see contract); add it to
`api/pyproject.toml` and `uv.lock` first.

## 1. PHASES P02 mandatory tests

| Rule | Tests |
| --- | --- |
| Same 5,000-row supplier file twice: 0 duplicates created, report shows 5,000 duplicates (blueprint 8 C3); gate < 60 s | `integration/imports/test_import_performance.py::test_same_5000_row_supplier_file_twice_creates_zero_duplicates` (times validate to completed of each run; checks DB uniqueness by GSTIN and by name + city; report `Summary` and 5,000 `Rows` lines with reasons; second confirm needs the partial flag) |
| Duplicate supplier by GSTIN, and by name + city, reported not merged | `integration/imports/test_import_classification.py::test_duplicate_supplier_by_gstin_reported_not_merged`, `::test_duplicate_supplier_by_name_and_city_reported_not_merged`, `::test_duplicate_part_by_part_no_reported`, `::test_duplicate_supplier_part_reported`; `unit/test_import_normalise.py` (natural keys) |
| Partial import requires explicit confirmation | `test_import_classification.py::test_partial_import_requires_explicit_confirmation`, `::test_a_batch_with_only_valid_rows_needs_no_partial_flag`, `::test_confirm_records_the_partial_decision_in_the_audit_log_and_emits_import_confirmed`; E2E `imports.spec.ts` error path; `web/src/lib/import-wizard.test.ts` |
| Contact disable / replace call the revocation hook; replaced contact keeps its history | `integration/masters/test_contacts_lifecycle.py::test_disable_contact_calls_the_revocation_hook_inside_the_transaction`, `::test_replace_contact_calls_the_revocation_and_replaced_hooks_in_the_transaction`, `::test_replaced_contact_keeps_its_history`, `::test_a_failing_revocation_hook_rolls_the_disable_back`, `::test_a_failing_replaced_hook_leaves_no_new_contact_and_the_old_one_active`, `::test_a_rejected_disable_never_reaches_the_hook` |
| Status change without a reason or without `can_approve` rejected; activity_log has before/after | `integration/masters/test_supplier_status.py::test_change_status_without_reason_rejected` (7 reasons), `::test_change_status_without_can_approve_rejected` (quality and admin), `::test_change_status_logs_before_after`, `::test_change_status_emits_exactly_one_supplier_status_changed_event`, `::test_status_change_business_audit_and_outbox_rows_commit_together` |
| CSV/Excel formula injection neutralised in exported reports | `integration/imports/test_import_report.py::test_export_neutralises_formula_injection`, `::test_report_cells_are_never_stored_as_formulas`; `unit/test_excel_safety.py` (all six lead characters, numbers untouched, idempotent) |
| Gate: UI E2E import wizard happy path and error path | `web/e2e/imports.spec.ts`: `happy path: upload, map, validate, preview, confirm, result with the report download`, `error path: errors and duplicates are listed, and a partial import needs an explicit tick`, `uploading the same file again shows the file-hash warning ...`, `importing the same file twice reports every row of the second run as a duplicate` |

## 2. INVARIANTS rows owned by P02

| Invariant | Tests |
| --- | --- |
| INV-PLT-01 (new tables in the RLS tests) | `integration/db/test_rls_platform_tables.py` and `test_supplier_policies.py` now parametrised over `tests/factories/rows.py::TABLES` (7 P01 + 9 P02 tables); `integration/db/test_masters_schema.py::test_p02_tables_use_tenant_policy_and_deny_suppliers_by_default`; the generic catalog tests in `test_schema_conventions.py` cover the new tables automatically (`supplier_contacts_mobile_idx` added to the documented tenant-first exceptions) |
| INV-PLT-04 (audit + outbox in one transaction) for every masters command | `integration/masters/test_masters_commands_audit.py::test_command_writes_one_activity_log_row_and_one_outbox_event_in_the_same_transaction` (21 commands), `::test_a_command_that_fails_validation_writes_no_audit_row_and_no_event`; imports: `imports/test_import_upload_and_mapping.py::test_each_import_command_writes_an_activity_log_row_on_the_batch` |
| INV-PLT-06 (no status field on `/update`) | `masters/test_catalog_api.py::test_supplier_part_update_cannot_change_status_supplier_or_part`; the P01 route scan `test_no_route_accepts_status_field_outside_commands` covers the new routes |
| INV-PLT-08 archive, never delete | `masters/test_suppliers_api.py::test_supplier_archive_sets_archived_at_and_keeps_references`, `::test_archive_requires_a_reason`, `::test_archiving_an_archived_supplier_is_409_invalid_transition`, `::test_archived_suppliers_are_hidden_from_the_default_list_and_shown_with_archived_true`; `masters/test_catalog_api.py::test_archived_part_hidden_from_capture_search`, `::test_unlinking_a_customer_part_archives_it`, `::test_archiving_a_supplier_part_removes_it_from_lists_and_keeps_the_row`; `db/test_masters_schema.py::test_identity_and_creation_columns_are_never_updatable_and_nothing_is_deletable` (9 tables); `imports/test_import_classification.py::test_row_matching_an_archived_supplier_goes_to_review` |
| INV-PLT-10 viewer cannot call any command | `masters/test_masters_authorization.py::test_viewer_cannot_call_any_p02_command` (28 explicit paths), plus the P01 dynamic `test_viewer_cannot_call_any_command` and `unit/test_permissions.py` loops over `all_commands()`; `unit/test_masters_registry.py` (28 commands registered, permissions) |
| INV-PLT-15 event catalogue | `unit/test_outbox_unit.py` (`SUPPLIER_STATUS_CHANGED` is no longer xfail), `unit/test_masters_registry.py::test_p02_derived_events_are_registered_with_an_emitter` |
| INV-PLT-16 migrations up/down/up | `migrations/test_masters_migration.py` (3 tests); `test_platform_migration.py` adapted: head is no longer `0002` (see section 5) |
| INV-MST-01 `customer_parts` many-to-many | `masters/test_catalog_api.py::test_part_can_link_to_many_customers`, `::test_create_part_has_no_customer_id_anywhere`; `db/test_masters_schema.py::test_part_can_link_to_many_customers_in_the_schema`, `::test_parts_has_no_customer_id_column`, `::test_customer_part_pair_is_unique` |
| INV-MST-02 status values, change only by the command | `db/test_masters_schema.py::test_supplier_status_accepts_the_five_values`, `::test_supplier_status_rejects_other_values`; `masters/test_supplier_status.py` (all of it, incl. 20 transitions `test_every_status_can_move_to_every_other_status_with_a_reason` and same-status 409); `masters/test_suppliers_api.py::test_create_supplier_requires_a_status` |
| INV-MST-03 `status*` written only by the status command | `masters/test_suppliers_api.py::test_supplier_update_command_ignores_status_fields` (7 fields), `::test_a_valid_update_leaves_every_status_column_untouched`. The CI half of the invariant (a source scan) is not written: it would need to read `app/`; the verifier should grep `app/masters` for writes to `status*` outside `change_status` |
| INV-MST-04 replace (hook part) | `masters/test_contacts_lifecycle.py::test_replace_contact_calls_the_revocation_and_replaced_hooks_in_the_transaction`, `::test_replace_contact_creates_the_new_contact_disables_the_old_and_links_them`, `::test_the_quality_contact_flag_moves_to_the_replacement`; links, sessions and SCAR reassignment (`test_replace_contact_revokes_links_and_sessions`, `test_replace_contact_reassigns_open_scars`) are P05 |
| INV-MST-05 disable needs a reason (hook part) | `masters/test_contacts_lifecycle.py::test_disable_contact_requires_reason`, `::test_disable_contact_makes_it_inactive_with_reason_and_timestamp`, `::test_disabling_a_disabled_contact_is_409_and_does_not_call_the_hook`; DB CHECK: `db/test_masters_schema.py::test_an_inactive_contact_needs_disabled_at_and_a_reason` |
| INV-IMP-01 file hash | `imports/test_import_upload_and_mapping.py::test_same_file_hash_flagged_before_processing`, `::test_a_file_that_differs_by_one_byte_is_not_flagged`, `::test_file_hash_flag_never_crosses_tenants`; E2E file-hash warning |
| INV-IMP-02 natural keys + row hash (suppliers, parts) | the duplicate tests of section 1; `unit/test_import_normalise.py`; `imports/test_import_classification.py::test_identical_rows_have_the_same_row_hash_across_batches_and_different_rows_differ`, `::test_duplicates_inside_one_file_point_at_the_first_row`, `::test_supplier_with_neither_gstin_nor_city_is_rejected_because_it_cannot_be_deduplicated` |
| INV-IMP-04 never merged or updated | `test_import_classification.py::test_changed_row_with_same_natural_key_goes_to_review_not_update` (supplier, part, supplier_part; snapshots of all three tables unchanged) |
| INV-IMP-05 report | `imports/test_import_report.py::test_import_report_counts_reconcile_to_rows_received`, `::test_import_report_has_reason_per_non_imported_row`, `::test_report_echoes_the_mapped_values_of_each_row`, `::test_report_download_is_an_xlsx_attachment`; `test_import_classification.py::test_every_received_row_gets_an_import_record_with_final_status_and_hash`; `web/src/lib/import-wizard.test.ts` (`reconciles`) |
| INV-IMP-06 partial import | section 1 |
| INV-IMP-08 formula injection | section 1 |
| INV-SEC-01 tenant isolation (P02 part) | `security/test_tenant_isolation_masters.py`: `test_tenant_a_cannot_read_tenant_b_suppliers_api`, `test_tenant_a_cannot_write_tenant_b_supplier_api`, contacts, parts/customers/links, lists, cross-tenant links, import batches (read and drive), confirm with a valid key; `imports/test_import_concurrency.py::test_a_validate_job_sent_under_tenant_a_cannot_touch_tenant_bs_batch`, `::test_an_import_job_sent_under_tenant_a_cannot_import_tenant_bs_batch`, `::test_a_job_message_without_a_tenant_id_never_runs`; `imports/test_import_upload_and_mapping.py::test_a_key_from_another_tenant_cannot_be_imported`, `::test_mapping_suggestion_never_comes_from_another_tenant` |
| INV-SEC-03 / INV-SEC-05 export | `test_import_report.py::test_viewer_cannot_export_excel`, `::test_export_writes_activity_log`, `::test_reading_a_batch_writes_no_audit_rows_only_the_export_does`, `::test_export_is_rate_limited_to_twenty_per_hour_per_user`, `::test_export_limit_is_per_user_not_per_tenant`; `masters/test_masters_authorization.py::test_imports_are_visible_to_quality_and_admin_only` |

## 3. Plan section 4 edge cases

| Edge case | Test |
| --- | --- |
| Same file twice, second confirm imports 0 and reports all as duplicates | performance test (5,000 rows); E2E `importing the same file twice ...` |
| Duplicates inside one file point at the first row | `test_duplicates_inside_one_file_point_at_the_first_row` |
| Supplier without GSTIN: name + city key, normalised; without both: rejected | `unit/test_import_normalise.py`, `test_duplicate_supplier_by_name_and_city_reported_not_merged`, `test_supplier_with_neither_gstin_nor_city_...` |
| Changed values with the same key go to review | section 2 INV-IMP-04 |
| `supplier_parts` with a missing supplier code or part: unmapped, reason names it | `test_supplier_part_with_an_unknown_supplier_code_or_part_is_unmapped_naming_the_reference` |
| Excel: empty rows skipped, merged headers, spaces, numeric GSTIN/part_no, dates ignored, `=` cells as text | `test_empty_rows_are_skipped_and_not_counted_but_row_numbers_stay_physical`, `test_merged_header_cells_do_not_break_column_detection`, `test_only_the_first_sheet_is_read`, `test_leading_and_trailing_spaces_are_trimmed_on_import`, `test_numeric_gstin_read_as_a_number_is_cleaned_to_text`, `test_numeric_part_no_read_as_float_is_cleaned_to_an_integer_string`, `test_unmapped_extra_columns_including_dates_are_ignored`, `test_a_cell_starting_with_equals_is_stored_as_text_not_evaluated`, `unit::test_clean_cell` |
| CSV encodings: UTF-8 with/without BOM; others rejected with a message | `test_csv_columns_are_detected_with_or_without_a_byte_order_mark`, `test_csv_in_another_encoding_is_rejected_and_never_becomes_a_batch` (cp1252, utf-16), `test_hindi_text_in_a_utf8_file_is_imported_intact` |
| Formula injection in report cells | section 1 |
| Archived masters out of pickers and import matching | INV-PLT-08 row |
| Status change: no reason 422, no `can_approve` 403, same status 409 | `test_supplier_status.py` |
| Supplier update never touches status: 422 | `test_supplier_update_command_ignores_status_fields` |
| Replace of a disabled contact 409; replace with itself 422 | `test_replacing_an_already_disabled_contact_is_409`, `test_a_contact_cannot_be_replaced_twice`, `test_a_contact_cannot_be_replaced_with_itself`; DB CHECK `test_a_contact_cannot_be_replaced_by_itself` |
| Concurrent confirm: one wins, one gets 409 | `imports/test_import_concurrency.py::test_concurrent_confirm_of_the_same_batch_one_wins_and_the_other_gets_409` (3 rounds, `threading.Barrier`), `::test_two_requests_with_the_same_idempotency_key_import_once`, `::test_a_cancel_racing_a_confirm_leaves_a_consistent_batch` |
| Cancel after confirm: 409 | `test_forbidden_batch_transition_is_409_invalid_transition_and_changes_nothing[importing-cancel]` and `[completed-cancel]` |
| Confirm-time revalidation | `test_confirm_revalidates_rows_that_became_duplicates_after_the_preview`, `test_confirm_revalidation_rejects_a_code_taken_after_the_preview` |

## 4. Other P02 plan test-list items

| Item | Tests |
| --- | --- |
| Constraints and grants (DB) | `integration/db/test_masters_schema.py` (146 cases: status/category/GSTIN/E.164/consent/ppm_target/import CHECKs, uniques, composite FKs, append-only `import_records`, column grants, indexes of DATA_MODEL 0.7) |
| Batch state machine, allowed and forbidden | `test_forbidden_batch_transition_is_409_invalid_transition_and_changes_nothing` (15 pairs), `test_a_batch_can_be_cancelled_until_it_is_confirmed`, `test_validate_moves_a_mapped_batch_to_validated_with_counts_and_no_master_rows`, `test_records_are_empty_until_confirm_and_preview_is_not_available_before_validate` |
| Mapping saved per tenant, prefilled (A-113) | `test_mapping_is_prefilled_from_the_tenants_last_mapping_for_that_entity`, `test_prefilled_mapping_drops_columns_the_new_file_does_not_have`, `test_map_*` |
| Upload validation (A-112, A-114) | `test_entities_not_built_in_p02_or_unknown_are_rejected`, `test_file_name_must_be_xlsx_or_csv`, `test_a_file_that_failed_the_scan_cannot_become_a_batch`, `test_a_key_that_is_not_an_import_upload_is_refused`, `test_a_corrupt_workbook_is_a_clean_client_error_never_a_server_error` |
| Supplier list: search, filters, sorts, keyset (API.md 5, 5.1) | `masters/test_suppliers_api.py` (search incl. `%`/`_` literal, status/category filters, three sorts, invalid sort 400, keyset over every sort, ties, insert between pages, cursor of another sort, limit bounds, tampered cursor) |
| Contacts: create/update, quality contact, consent, `needs_reverification` boundaries, PII masking in audit | `masters/test_contacts_api.py` |
| Contact OTP (A-78, A-110): 6 digits, 10 min TTL, 5 attempts, 3 sends per hour, worker-only send, no oracle, hashed in Redis | `masters/test_contacts_otp.py` |
| Customers, parts, customer_parts, supplier_parts | `masters/test_catalog_api.py` (ppm_target > 0, strict integer, pair uniqueness, filters, keyset by `part_no`) |
| Role matrix | `masters/test_masters_authorization.py` (viewer 403, anonymous 401, quality/admin not blocked, change-status needs can_approve, reads for every role, imports Q only) |
| Idempotency on commands | `test_create_supplier_with_an_idempotency_key_creates_one_row`, `test_change_status_replays_for_the_same_idempotency_key_and_logs_once`, `test_contact_commands_replay_with_an_idempotency_key`, `test_catalog_commands_replay_with_an_idempotency_key`, confirm tests |

## 4b. Decisions A-116 to A-120

| Decision | Tests |
| --- | --- |
| A-116 create status gate | `masters/test_suppliers_api.py::test_create_supplier_without_can_approve_cannot_choose_a_status_other_than_approved` (quality and admin x 4 statuses: 403, no row, no audit, no event), `::test_create_supplier_without_can_approve_may_create_an_approved_supplier`, `::test_create_supplier_with_can_approve_may_choose_any_of_the_five_statuses` |
| A-117 links created active | `masters/test_catalog_api.py::test_a_new_supplier_part_link_is_active_and_create_takes_no_status`, `::test_supplier_part_update_cannot_change_status_supplier_or_part`, `::test_create_supplier_part_defaults_to_active_and_keeps_ppm_target` |
| A-118 cross-key match goes to review | `imports/test_import_classification.py::test_a_row_matching_an_existing_supplier_by_name_and_city_under_another_gstin_goes_to_review` (3 shapes), `::test_the_cross_key_rule_also_applies_within_one_file` (3 shapes), `::test_a_gstin_row_with_no_name_and_city_match_is_still_valid`, `::test_two_rows_with_the_same_name_and_city_and_no_gstin_are_still_plain_duplicates` |
| A-119 restore archived link | `masters/test_catalog_api.py::test_linking_an_archived_customer_part_pair_restores_the_same_row`, `::test_linking_an_archived_supplier_part_pair_restores_the_same_row`, `::test_the_same_customer_part_pair_cannot_be_linked_twice` (409), `::test_a_supplier_part_pair_is_unique_and_references_must_exist` (409) |
| A-120 browser upload | contract 5.4 only; covered by the E2E upload steps of `imports.spec.ts` |

## 5. Existing tests changed

Strengthened or extended only; none weakened.

- `tests/factories/rows.py`: `INSERTERS`/`TABLES` now include the nine P02 tables, so every P01 parametrised RLS, supplier-deny and
  no-tenant test (`test_rls_platform_tables.py`, `test_supplier_policies.py`) also runs for them. The new parametrisations
  fail until migration `0003` exists; the 7 P01 parametrisations are unchanged and still pass.
- `test_rls_platform_tables.py`: the update-hijack test also covers `suppliers`, `parts`, `customers`.
- `test_schema_conventions.py`: `supplier_contacts_mobile_idx` joins the documented tenant-first exceptions (DATA_MODEL 0.4).
- `test_outbox_unit.py`: `SUPPLIER_STATUS_CHANGED` is a real test now (`BUILT_PHASES = {"P01","P02"}`); the other 18 stay `xfail(strict)`.
- `test_platform_migration.py`: with a third revision, "head follows 0001" became "revision 0002 follows 0001"; the
  "downgrade one step removes the platform objects" test now downgrades to `0001` (the new `test_masters_migration.py`
  tests the one-step case for `0003`).
- `tests/conftest.py`: fixture `drain` (in-process `imports` worker).
- `web/playwright.config.ts`: `phone-360` runs `smoke.spec.ts` and `*.phone.spec.ts`; `desktop-1440` skips the phone specs; global timeouts.

## 6. Not covered in P02, by design

Magic links, sessions and SCAR reassignment on disable/replace (P05); contact anonymisation (P05); receipts/NCR imports
and `test_same_5000_row_receipt_file_twice_creates_zero_duplicates` (P04); `certificates_meta` (P03); generic exports (P08);
the supplier-scoped RLS of `parts` and `supplier_contacts` (P04/P05); inline-edit and contact verification/consent/replace
screens are covered at API level only (E2E covers add and disable contacts, and the status dialog).
