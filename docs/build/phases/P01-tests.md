# P01 tests: spec rule to test name

Paths are relative to `api/tests/`. Names are the INVARIANTS.md names where one exists. Interfaces the tests assume
are in `P01-test-contract.md`. Fixtures: `conftest.py` (role guard, `_test_env`, `api`, `seeded`, `seeded_pair`,
`redis_client`, `mailbox`, `clean_outbox`); factories in `factories/`.

## PHASES P01 mandatory tests

| Mandatory test | Tests |
| --- | --- |
| Tenant A cannot read/write Tenant B rows through the API | `security/test_tenant_isolation_api.py`: `test_tenant_a_cannot_read_tenant_b_users_api`, `..._plants_api`, `test_tenant_a_cannot_update_tenant_b_user_api`, `..._deactivate_tenant_b_user_api`, `..._update_tenant_b_plant_api`, `test_foreign_and_nonexistent_ids_are_indistinguishable`, `test_cross_tenant_actions_leave_no_audit_or_outbox_trace_in_either_tenant`, `test_sessions_do_not_cross_tenants_on_a_shared_connection_pool` |
| ... through a raw ORM session | `security/test_tenant_isolation_orm.py` (6 tests); `integration/db/test_rls_platform_tables.py::test_tenant_a_cannot_read_tenant_b_rows_raw_session`, `test_tenant_a_cannot_insert_row_for_tenant_b` (parametrised over all 7 tables) |
| ... through a worker | `integration/worker/test_worker_jobs.py::test_worker_job_cannot_read_other_tenant`, `test_worker_job_cannot_write_for_another_tenant`, `test_consecutive_jobs_for_different_tenants_on_one_pooled_connection_do_not_leak_context` |
| Command writes activity_log + outbox in the same transaction; failure rolls back both | `integration/commands/test_command_audit_and_outbox.py::test_command_writes_activity_log_and_outbox_in_same_transaction` (6 commands, equal `xmin`), `test_command_failure_rolls_back_activity_log_and_outbox` (outbox fails / activity_log fails / idempotent response store fails), `test_idempotency_row_is_written_in_the_same_transaction_as_the_business_change`, `test_a_validation_failure_writes_no_audit_no_outbox_and_no_idempotency_row` |
| Outbox processed exactly once under two concurrent workers; retries then dead-letter | `integration/outbox/test_dispatcher.py::test_outbox_event_processed_once_with_two_concurrent_dispatchers` (barrier), `test_app_claim_outbox_batch_skip_locked_returns_disjoint_batches_to_open_transactions`, `test_outbox_retry_backoff_increases_exponentially`, `test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted`; `integration/worker/test_worker_jobs.py::test_job_dead_lettered_after_5_attempts`, `test_dead_lettered_job_recorded_in_job_dead_letters` |
| Viewer cannot call any command; `can_approve` required where flagged | `integration/commands/test_permissions_api.py::test_viewer_cannot_call_any_command` (parametrised over the route table plus the API.md 3.1 list); `unit/test_permissions.py::test_requires_can_approve_matrix`, `test_can_approve_commands_reject_without_flag`, `test_viewer_denied_on_every_registered_command_at_permission_level` |
| Signed URL expires (<= 15 min); unauthorised user cannot download | `integration/files/test_upload_url_api.py::test_signed_url_expires_within_15_minutes`, `test_unauthorised_user_cannot_get_signed_url`; `integration/files/test_presigned_download.py::test_signed_url_expires_within_15_minutes`, `test_the_signed_url_downloads_the_object_and_then_actually_expires`, `test_unauthorised_user_cannot_get_signed_url`, `test_tenant_a_cannot_get_signed_url_for_tenant_b_file`, `test_unscanned_file_not_downloadable` |
| Migrations up/down/up | `integration/migrations/test_platform_migration.py::test_migrations_up_down_up` (+ one-step downgrade, single head, post round trip RLS check) |

## INVARIANTS.md rows (P01)

| Invariant | Tests |
| --- | --- |
| INV-PLT-01 | `integration/db/test_schema_conventions.py::test_every_table_has_tenant_id_and_forced_rls`; `integration/db/test_rls_platform_tables.py::test_tenant_a_cannot_read_tenant_b_rows_raw_session`, `test_tenant_a_cannot_insert_row_for_tenant_b`, `test_composite_fk_rejects_cross_tenant_reference`; also `test_every_foreign_key_between_tenant_tables_is_composite_on_tenant_id`, `test_every_tenant_id_references_tenants_with_on_delete_restrict`, `test_every_table_has_unique_tenant_id_id_for_composite_foreign_keys`, `test_every_index_starts_with_tenant_id_except_documented_system_lookups` |
| INV-PLT-02 | `integration/db/test_rls_platform_tables.py::test_no_tenant_context_returns_zero_rows`, `test_no_tenant_context_insert_rejected`, `test_empty_string_tenant_context_behaves_like_unset`, `test_malformed_tenant_context_fails_closed`, `test_tenant_guc_does_not_leak_into_the_next_transaction_on_a_reused_connection` |
| INV-PLT-03 | `integration/worker/test_worker_jobs.py::test_worker_job_runs_with_job_tenant_context`, `test_worker_job_cannot_read_other_tenant`, `test_job_without_a_valid_tenant_id_is_rejected_and_never_runs`; `integration/db/test_tenant_tx.py` (7 tests) |
| INV-PLT-04 | see mandatory row; plus `integration/commands/test_command_audit_and_outbox.py::test_activity_log_records_actor_session_and_ip`, `test_activity_log_create_has_no_before_and_an_after_snapshot`, `test_activity_log_update_captures_before_after_and_reason`, `test_role_change_audit_row_shows_before_after_and_reason`, `test_activity_log_snapshots_never_contain_password_hashes`, `test_created_by_and_updated_by_record_the_acting_user`, `test_login_is_audited_as_a_session_start` |
| INV-PLT-05 | `integration/db/test_constraints_platform.py::test_activity_log_update_rejected_db`, `test_activity_log_delete_rejected_db`, `test_activity_log_append_only_trigger_blocks_even_when_privileges_are_granted` |
| INV-PLT-06 | `integration/commands/test_permissions_api.py::test_no_route_accepts_status_field_outside_commands`, `test_route_table_has_no_put_patch_or_delete_on_the_api`, `test_every_post_route_is_a_registered_command_or_a_documented_non_command`; `integration/commands/test_platform_commands_api.py::test_update_cannot_change_active_state_only_deactivate_does` |
| INV-PLT-07 | `integration/db/test_constraints_platform.py::test_app_role_has_no_delete_privilege_on_domain_tables`, `test_app_role_cannot_truncate_or_alter_any_table` |
| INV-PLT-09 | `integration/db/test_constraints_platform.py::test_user_plant_ids_must_exist_in_tenant_db`; API side `test_create_user_rejects_a_plant_from_another_tenant_without_creating_the_user`, `test_update_user_plant_ids_validates_tenant_membership` |
| INV-PLT-10 | mandatory row; `integration/commands/test_permissions_api.py` (401 for all, quality denied admin commands, authorisation before validation/lookup, read matrix); `unit/test_permissions.py` |
| INV-PLT-11 | `unit/test_import_boundaries.py::test_api_layer_cannot_import_provider_clients`; `integration/auth/test_password_reset.py::test_external_send_carries_idempotency_key`, `test_the_api_request_itself_sends_nothing_external_only_the_worker_does`, `test_reset_email_carries_an_idempotency_key_header` |
| INV-PLT-12 | `integration/outbox/test_dispatcher.py::test_outbox_event_processed_once_with_two_concurrent_dispatchers` |
| INV-PLT-13 | `test_outbox_retry_backoff_increases_exponentially`, `test_outbox_event_dead_lettered_after_5_attempts_and_alert_emitted`, `test_job_dead_lettered_after_5_attempts`; `unit/test_outbox_unit.py::test_backoff_is_five_seconds_times_two_to_the_attempts`, `test_max_attempts_is_five` |
| INV-PLT-14 | `integration/commands/test_idempotency.py::test_idempotency_key_replays_original_response`, `test_idempotency_key_reuse_with_different_body_rejected`, `test_same_key_while_the_first_request_is_in_flight_is_409_conflict`, scope per actor and per tenant, 24 h expiry |
| INV-PLT-15 | `unit/test_outbox_unit.py::test_event_catalogue_contains_every_22_3_event_as_non_derived` (19), `test_event_catalogue_every_22_3_event_has_emitter` (19, strict xfail with the phase named in each reason), `test_platform_events_are_registered_as_derived_names` |
| INV-PLT-16 | `integration/migrations/test_platform_migration.py::test_migrations_up_down_up` |
| INV-PLT-18 | `integration/db/test_definer_functions.py::test_definer_functions_have_safe_search_path` (+ exactly three functions, schema-qualified tables, EXECUTE for the app role only, ids only); `integration/db/test_constraints_platform.py::test_public_has_no_temp_or_create_privilege` |
| INV-PLT-19 | `integration/db/test_data_migration_rule.py::test_data_migrations_set_tenant_guc_and_assert_counts`, abort test, static scan of migrations |
| INV-PLT-20 | `integration/worker/test_worker_jobs.py::test_dead_lettered_job_recorded_in_job_dead_letters`, no-duplicate row, ids-only payload |
| INV-PLT-21 | `integration/db/test_schema_conventions.py::test_all_views_are_security_invoker` (+ negative control) |
| INV-PLT-22 | `integration/db/test_supplier_policies.py::test_supplier_actor_type_value_consistent` |
| INV-SUP-09 (P01 part) | `test_every_rls_table_has_supplier_policy` (P00 file, now live), `integration/db/test_schema_conventions.py::test_every_rls_table_has_tenant_policy_and_supplier_policy`, `test_supplier_scoped_tables_are_exactly_the_documented_p01_list`; `integration/db/test_supplier_policies.py` (deny matrix, insert-only audit/outbox, `RETURNING` fails, idempotency scoping), `test_supplier_rls_denies_unlisted_tables_db` |
| INV-SEC-01 (P01 part) | API/ORM/worker files above; `integration/files/test_presigned_download.py::test_tenant_a_cannot_get_signed_url_for_tenant_b_file` |
| INV-SEC-02 | see mandatory row |
| INV-SEC-04 | `integration/auth/test_password_reset.py::test_password_stored_as_argon2id`; `integration/auth/test_login_rate_limit_and_csrf.py::test_login_rate_limited`; `integration/auth/test_login_and_sessions.py::test_session_cookie_flags_secure_httponly_samesite` |
| INV-SEC-08 | `security/test_redis_acl.py::test_redis_app_user_cannot_run_admin_commands` (+ AUTH required, default user disabled, key patterns) |
| INV-AI-02 | `unit/test_permissions.py::test_ai_actor_denied_on_every_command` |
| INV-DOC-10 (P01 part) | `integration/files/test_upload_url_api.py::test_upload_rejects_wrong_content_type`, `test_upload_rejects_over_20_mb`; `integration/files/test_presigned_download.py::test_unscanned_file_not_downloadable`; `integration/files/test_scan_job.py` |

## Plan section 4 edge cases

| Edge case | Test |
| --- | --- |
| No tenant GUC: zero rows, insert rejected; no leak from a previous transaction; pooled connection reuse | `test_no_tenant_context_*`, `test_tenant_guc_does_not_leak_into_the_next_transaction_on_a_reused_connection`, `test_guc_does_not_survive_tenant_tx_on_the_reused_pooled_connection`, `test_consecutive_jobs_for_different_tenants_on_one_pooled_connection_do_not_leak_context` |
| `INSERT ... RETURNING` never used on activity_log / outbox | `test_supplier_insert_returning_fails_which_is_why_writers_never_use_returning` (every supplier-path command test would fail otherwise) |
| Login: unknown email, wrong password, inactive, no password, rate limited; timing equalised | `test_login_failures_return_one_generic_error_whatever_the_cause`, `test_login_runs_a_password_verification_even_when_there_is_nothing_to_verify_against`, `unit/test_passwords.py::test_verify_password_with_no_stored_hash_still_runs_an_argon2_verification`, rate limit tests |
| Deactivated user: sessions rejected at once | `test_deactivating_a_user_rejects_all_their_existing_sessions_immediately`, `test_failed_deactivation_does_not_end_the_users_sessions` |
| Session idle and absolute expiry; CSRF missing / mismatched / wrong Origin | `test_a_session_is_rejected_after_eight_hours_without_activity`, `test_activity_slides_the_idle_window`, `test_a_session_is_rejected_after_seven_days_even_if_continuously_active`; `test_login_rate_limit_and_csrf.py` CSRF block |
| Idempotency: replay, mismatch 422, concurrent 409, per-actor scope | `integration/commands/test_idempotency.py` |
| Command raising after the mutation persists nothing | `test_command_failure_rolls_back_activity_log_and_outbox` |
| Outbox: two dispatchers once; failure -> attempts + backoff; 5th -> dead + alert | `integration/outbox/test_dispatcher.py` |
| Worker message without tenant_id rejected; job sees only its tenant | `test_job_without_a_valid_tenant_id_is_rejected_and_never_runs`, `test_files_scan_job_without_tenant_id_is_rejected_and_nothing_is_promoted` |
| `users.plant_ids` of another tenant rejected | `test_user_plant_ids_must_exist_in_tenant_db` |
| Upload: > 20 MB 413; type 415; magic-byte mismatch and EICAR quarantined; foreign prefix 404; URL <= 15 min | `integration/files/*` |
| Viewer: every command 403; original download 403 (A-70) | `test_viewer_cannot_call_any_command`, `test_unauthorised_user_cannot_get_signed_url_viewer_matrix` |
| AI actor denied on every command | `test_ai_actor_denied_on_every_command` |

## Other covered rules

- Platform command bodies, validation, reasons, 404s: `integration/commands/test_platform_commands_api.py`.
- Role matrix for reads: `test_read_endpoints_follow_the_role_matrix`; keyset pagination and bad cursor: `test_users_list_is_tenant_scoped_keyset_paginated_and_never_exposes_password_hash`, `test_tampered_or_garbage_cursor_is_400_bad_request`.
- Constraints A-90 (plant code regex, E.164 mobile), A-03 (global email), STD columns, grants, triggers: `integration/db/test_constraints_platform.py`, `test_schema_conventions.py`.
- Error format and DB error mapping: `unit/test_errors.py`; real endpoints: `integration/errors/test_observability_and_limits.py`.
- Logs: request id / tenant / actor / route / status / duration, PII masked, secrets redacted: `unit/test_logging_pii.py`, `integration/errors/test_observability_and_limits.py`.
- Password reset by OTP (hashed, 15 min TTL, 5 attempts, single use, 3/hour): `integration/auth/test_password_reset.py`.
- Scheduler leader lock and fan-out, `core.sweep_pending` stub, worker wiring: `integration/worker/test_scheduler.py`, `test_worker_jobs.py`.
- Seed: `integration/test_seed_demo.py`. Primitives: `unit/test_core_primitives.py`. State machine guard: `unit/test_state_machine.py`.

## Not covered in P01 (and why)

- Blueprint 24.1 rule 4 formula cases: no formula exists in P01 (money/time primitives only).
- `core.hooks` in-transaction hooks: no P01 command registers one, so there is no observable behaviour beyond session kill on deactivation.
- Coverage >= 90% on `app/core` is a gate, not a test: the verifier runs `pytest --cov`.
- Playwright E2E: P01 has no UI (A-93).

## Tests that pass before implementation (15, none is a P01 feature test)

- `test_public_has_no_temp_or_create_privilege`: the P00 baseline already meets D-3.
- `test_every_data_changing_migration_uses_the_per_tenant_helper`: static scan; no data migration exists yet. It fails the day one appears without the helper.
- `test_all_views_are_security_invoker` (no views yet) and `test_view_introspection_detects_a_view_without_security_invoker` (the negative control that proves the check is not vacuous).
- `test_test_connections_are_the_app_role`, `test_tenant_guc_does_not_survive_a_rolled_back_transaction`: properties of the P00 role setup and the test guard.
- `test_app_user_can_use_the_documented_key_patterns` (7 key families): pass on the open dev Redis; after the ACL lands they protect against an ACL that is too tight.
- `test_scanner_detects_a_provider_import`, `test_blueprint_22_3_lists_nineteen_events`: self-checks of the test helpers.

Every introspection loop (`tenant_tables`, `_definers`, route scans) asserts its subject exists first, so none can pass on an empty schema.
