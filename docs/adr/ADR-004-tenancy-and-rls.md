# ADR-004 — Tenancy and row-level security (requests, workers, supplier sessions)

- Status: Accepted (2026-10-03)
- Spec: §6 ("Row-level security on tenant_id from the first migration"), §21.1, §21.2, §24.1.1

## Context
Shared database, many tenants. Isolation must hold even if application code forgets a filter, including in workers,
scheduler fan-out, supplier sessions and provider webhooks that arrive with no tenant context.

## Options considered
| Option | Pros | Cons |
| --- | --- | --- |
| A. App-level `WHERE tenant_id` only | simple | one missed filter = breach |
| B. **Shared schema + Postgres RLS (FORCE) + non-bypass app role + composite FKs** | DB-enforced; matches §6 | GUC discipline; a few cross-tenant lookups need SECURITY DEFINER functions |
| C. Schema per tenant | strong isolation | migrations × N; connection churn; not needed at Stage 1 |
| D. Database per tenant | strongest | ops cost; Stage 3 option only (SCALING.md S-16) |

## Decision
Option B.
1. Every table has `tenant_id`; `ENABLE` + `FORCE ROW LEVEL SECURITY`; policy `tenant_id = app_current_tenant_id()`
   for `USING` and `WITH CHECK`; unset GUC → NULL → no rows (fail closed). Template in DATA_MODEL.md §0.5.
2. Roles: `qualloop_owner` (migrations only), `qualloop_app` (runtime; NOBYPASSRLS; no DELETE on domain tables),
   `qualloop_sysfn` (NOLOGIN owner of a fixed set of SECURITY DEFINER lookup functions, with role-specific SELECT policies;
   no BYPASSRLS needed, so it works on managed Postgres).
3. Context propagation — always `set_config(…, true)` (transaction-local, safe with poolers):

| Path | How tenant is set |
| --- | --- |
| Internal request | session (Redis) → `tenant_id`; `db_tx` dependency sets `app.tenant_id`, `app.actor_type='user'`, `app.actor_id` |
| Worker job | every message carries `tenant_id`; Dramatiq middleware opens `tenant_tx(tenant_id, actor='system')`; jobs without tenant_id are rejected |
| Scheduler | `app_active_tenant_ids()` → one job per tenant |
| Outbox dispatcher | `app_claim_outbox_batch()` (definer) returns rows with tenant ids; per-row updates under that tenant's GUC |
| Supplier pre-OTP | `app_resolve_magic_link(sha256(token))` at exchange → signed `ql_pre` cookie `(tenant_id, magic_link_id)` → GUCs `actor_type='supplier_session'`, `actor_id`, `magic_link_id`, `scope_object_*`, `supplier_id` |
| Supplier session | HMAC-signed cookie `(tenant_id, session_id)` → GUCs as pre-OTP plus `supplier_session_id` → session row read under RLS (`id = app.supplier_session_id`) |
| Login | `app_resolve_login(email)` → tenant + user id |
| Webhooks | `app_resolve_provider_message(channel, id)` / `app_resolve_contacts_by_mobile(mobile)` |

4. Composite FKs `(tenant_id, x_id)` make cross-tenant references impossible even for the owner role.
5. **Suppliers are denied by default on every table.**
   - `enable_tenant_rls()` always adds the RESTRICTIVE `FOR ALL` policy `p_supplier_deny`, which requires `app_current_actor_type() IS DISTINCT FROM 'supplier_session'`.
   - Only the tables listed in DATA_MODEL.md §0.5 opt in, via `enable_supplier_scoped_rls(table, select_predicate, insert, update_predicate)`. That helper replaces the deny with per-command restrictive policies keyed on the supplier GUCs (`app.supplier_session_id`, `app.magic_link_id`, `app.scope_object_type`, `app.scope_object_id`, `app.supplier_id`, `app.actor_id`). It never allows DELETE.
   - A supplier may INSERT into `activity_log` and `outbox_events` but never SELECT from them.
   - CI test `test_every_rls_table_has_supplier_policy` fails if any table lacks either the deny policy or the full scoped set, or if the scoped set differs from the documented list.
   - One actor value is used everywhere: `supplier_session`.
6. Object storage keys are prefixed `t/{tenant_id}/`; the signed-URL service verifies the prefix equals the caller's tenant.
7. CI test `test_every_table_has_tenant_id_and_forced_rls` introspects `pg_class.relrowsecurity/relforcerowsecurity` for
   every table in the schema.

8. SECURITY DEFINER functions are declared with `SET search_path = pg_catalog, public, pg_temp` and use schema-qualified tables. The database has `REVOKE TEMP ON DATABASE … FROM PUBLIC` and `REVOKE CREATE ON SCHEMA public FROM PUBLIC` (D-3).
9. Data migrations switch with `SET LOCAL ROLE qualloop_app`, set the tenant GUC per tenant, and assert row counts per tenant (DATA_MODEL.md §0.9, D-7).
10. All views are `security_invoker = true`.

## Consequences
- Tests must run as `qualloop_app`, never as superuser, or RLS is silently bypassed.
- Any new definer function needs security review (ADR-019).

## Revisit when
- A tenant contract requires physical isolation (→ S-16), or
- RLS policy evaluation shows up as > 10% of query time in `EXPLAIN ANALYZE` on hot paths.
