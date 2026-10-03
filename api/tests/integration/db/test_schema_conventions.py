"""DATA_MODEL section 0 conventions, proven by catalog introspection on the migrated database.

INV-PLT-01 (tenant_id + forced RLS everywhere), INV-SUP-09 (supplier deny by default), INV-PLT-21 (views)."""

import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration

P01_TABLES = {
    "tenants",
    "plants",
    "users",
    "activity_log",
    "outbox_events",
    "idempotency_keys",
    "job_dead_letters",
}
# DATA_MODEL 0.5: the supplier-reachable tables that exist in P01 (others arrive with later phases).
P01_SUPPLIER_SCOPED = {"tenants", "activity_log", "outbox_events", "idempotency_keys"}
# DATA_MODEL 0.4 exceptions (cross-tenant system lookups) + 9 (idempotency_keys expiry index).
# P02 adds supplier_contacts_mobile_idx (DATA_MODEL 0.4: WhatsApp STOP arrives with only a phone number, A-67).
NON_TENANT_FIRST_INDEXES = {
    "users_email_uq",
    "outbox_events_pending_idx",
    "outbox_events_dead_idx",
    "supplier_contacts_mobile_idx",
}
IDEMPOTENCY_EXPIRY_TABLE = "idempotency_keys"


def tenant_tables(engine: Engine, *, require_p01: bool = True) -> set[str]:
    """Real domain tables: every base table in public except alembic_version and throwaway zz_ probes.

    By default asserts the P01 tables exist, so no introspection loop can pass vacuously on an empty schema."""
    tables = _tables(engine)
    if require_p01:
        assert tables >= P01_TABLES, (
            f"P01 tables missing from the migrated schema: {sorted(P01_TABLES - tables)}"
        )
    return tables


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
                "AND c.relkind IN ('r','p') AND c.relname <> 'alembic_version' "
                "AND c.relname NOT LIKE 'zz\\_%'"
            )
        )
        return {r[0] for r in rows}


def test_all_p01_tables_exist(owner_engine: Engine) -> None:
    assert tenant_tables(owner_engine, require_p01=False) >= P01_TABLES


def test_every_table_has_tenant_id_and_forced_rls(owner_engine: Engine) -> None:
    tables = tenant_tables(owner_engine)
    assert tables, "no tables migrated"
    with owner_engine.connect() as conn:
        for table in sorted(tables):
            col = conn.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t AND column_name = 'tenant_id'"
                ),
                {"t": table},
            ).one_or_none()
            assert col is not None, f"{table} has no tenant_id"
            assert tuple(col) == ("uuid", "NO"), f"{table}.tenant_id must be uuid NOT NULL"
            flags = conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = CAST(:t AS regclass)"
                ),
                {"t": f"public.{table}"},
            ).one()
            assert tuple(flags) == (True, True), f"{table}: RLS must be enabled AND forced"


STD_COLUMNS = {
    "id": ("uuid", "NO"),
    "tenant_id": ("uuid", "NO"),
    "created_at": ("timestamp with time zone", "NO"),
    "created_by": ("uuid", "YES"),
    "updated_at": ("timestamp with time zone", "NO"),
    "updated_by": ("uuid", "YES"),
}


def test_every_table_has_the_standard_columns_with_exact_types(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        for table in sorted(tenant_tables(owner_engine)):
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            )
            have = {r[0]: (r[1], r[2]) for r in rows}
            for name, expected in STD_COLUMNS.items():
                assert have.get(name) == expected, f"{table}.{name}: {have.get(name)} != {expected}"


def test_no_column_is_timestamp_without_time_zone(owner_engine: Engine) -> None:
    tenant_tables(owner_engine)
    with owner_engine.connect() as conn:
        bad = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'timestamp without time zone' "
                "AND table_name NOT LIKE 'zz\\_%'"
            )
        ).all()
    assert bad == []


def test_every_table_has_unique_tenant_id_id_for_composite_foreign_keys(
    owner_engine: Engine,
) -> None:
    sql = text(
        """
        SELECT i.indrelid::regclass::text
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        WHERE i.indisunique AND i.indnatts = 2 AND i.indpred IS NULL
          AND (SELECT array_agg(a.attname::text ORDER BY k.ord)
               FROM unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
               JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
              ) = ARRAY['tenant_id','id']
        """
    )
    with owner_engine.connect() as conn:
        have = {r[0] for r in conn.execute(sql)}
    missing = tenant_tables(owner_engine) - have
    assert missing == set(), f"no UNIQUE (tenant_id, id) on {sorted(missing)}"


def test_every_tenant_id_references_tenants_with_on_delete_restrict(owner_engine: Engine) -> None:
    sql = text(
        """
        SELECT c.conrelid::regclass::text, c.confdeltype, c.confupdtype
        FROM pg_constraint c
        WHERE c.contype = 'f' AND c.confrelid = 'public.tenants'::regclass
          AND (SELECT array_agg(a.attname::text) FROM unnest(c.conkey) k(attnum)
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum) = ARRAY['tenant_id']
        """
    )
    with owner_engine.connect() as conn:
        rows = {r[0]: (r[1], r[2]) for r in conn.execute(sql)}
    expected = tenant_tables(owner_engine) - {"tenants"}
    assert expected <= set(rows), f"missing tenant FK on {sorted(expected - set(rows))}"
    assert all(v == ("r", "a") for k, v in rows.items() if k in expected)  # RESTRICT / NO ACTION


def test_every_foreign_key_between_tenant_tables_is_composite_on_tenant_id(
    owner_engine: Engine,
) -> None:
    """DATA_MODEL 0.3: no FK can point at another tenant's row (vacuous until the first inter-table FK)."""
    tenant_tables(owner_engine)
    sql = text(
        """
        SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
          AND c.confrelid <> 'public.tenants'::regclass
        """
    )
    with owner_engine.connect() as conn:
        for table, name, definition in conn.execute(sql):
            if table.startswith("zz_"):
                continue
            assert "(tenant_id," in definition and "REFERENCES" in definition, (
                f"{table}.{name} is not composite on tenant_id: {definition}"
            )
            assert "ON DELETE CASCADE" not in definition, f"{table}.{name} cascades"


def test_every_index_starts_with_tenant_id_except_documented_system_lookups(
    owner_engine: Engine,
) -> None:
    tenant_tables(owner_engine)
    sql = text(
        """
        SELECT c.relname AS tbl, ic.relname AS idx, i.indisprimary,
               (SELECT a.attname FROM pg_attribute a
                 WHERE a.attrelid = i.indrelid AND a.attnum = i.indkey[0]) AS first_col,
               (SELECT string_agg(a.attname::text, ',' ORDER BY k.ord)
                  FROM unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
                  JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum) AS cols
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_class ic ON ic.oid = i.indexrelid
        WHERE c.relnamespace = 'public'::regnamespace AND c.relname NOT LIKE 'zz\\_%'
          AND c.relname <> 'alembic_version'
        """
    )
    offenders: list[str] = []
    with owner_engine.connect() as conn:
        for tbl, idx, is_primary, first_col, cols in conn.execute(sql):
            if is_primary or first_col == "tenant_id" or idx in NON_TENANT_FIRST_INDEXES:
                continue
            if tbl == IDEMPOTENCY_EXPIRY_TABLE and cols == "expires_at":
                continue
            offenders.append(f"{tbl}.{idx}({cols})")
    assert offenders == []


def test_system_lookup_indexes_exist_as_documented(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        defs = {
            r[0]: r[1]
            for r in conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                    "AND indexname IN ('users_email_uq','outbox_events_pending_idx','outbox_events_dead_idx')"
                )
            )
        }
    assert set(defs) == {"users_email_uq", "outbox_events_pending_idx", "outbox_events_dead_idx"}
    assert "UNIQUE" in defs["users_email_uq"] and "lower(email)" in defs["users_email_uq"]
    assert "processed_at IS NULL" in defs["outbox_events_pending_idx"]
    assert "attempts < 5" in defs["outbox_events_pending_idx"]
    assert "attempts >= 5" in defs["outbox_events_dead_idx"]


def _policies(engine: Engine) -> dict[str, set[str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, p.polname FROM pg_class c JOIN pg_policy p ON p.polrelid = c.oid "
                "WHERE c.relnamespace = 'public'::regnamespace"
            )
        )
        out: dict[str, set[str]] = {}
        for table, policy in rows:
            out.setdefault(table, set()).add(policy)
    return out


def test_every_rls_table_has_tenant_policy_and_supplier_policy(owner_engine: Engine) -> None:
    """INV-SUP-09: p_tenant plus either p_supplier_deny or the four p_supplier_* policies."""
    policies = _policies(owner_engine)
    scoped = {"p_supplier_select", "p_supplier_insert", "p_supplier_update", "p_supplier_delete"}
    for table in sorted(tenant_tables(owner_engine)):
        have = policies.get(table, set())
        assert "p_tenant" in have, f"{table} lacks p_tenant"
        assert "p_supplier_deny" in have or scoped <= have, f"{table} lacks a supplier policy"
        assert not ("p_supplier_deny" in have and scoped & have), (
            f"{table} has both deny and scoped"
        )


def test_supplier_scoped_tables_are_exactly_the_documented_p01_list(owner_engine: Engine) -> None:
    policies = _policies(owner_engine)
    scoped = {
        t
        for t in tenant_tables(owner_engine)
        if {"p_supplier_select", "p_supplier_insert"} <= policies.get(t, set())
    }
    assert scoped == P01_SUPPLIER_SCOPED
    denied = tenant_tables(owner_engine) - scoped
    assert all("p_supplier_deny" in policies[t] for t in denied)


def test_platform_system_policies_exist_for_definer_functions_only(owner_engine: Engine) -> None:
    policies = _policies(owner_engine)
    assert "tenants_sysfn" in policies["tenants"]
    assert "users_sysfn_login" in policies["users"]
    assert {"outbox_sysfn_select", "outbox_sysfn_update"} <= policies["outbox_events"]
    sql = text(
        "SELECT c.relname, p.polname, r.rolname FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
        "JOIN pg_roles r ON r.oid = ANY (p.polroles) WHERE p.polname LIKE '%sysfn%'"
    )
    with owner_engine.connect() as conn:
        rows = conn.execute(sql).all()
    assert rows and all(r[2] == "qualloop_sysfn" for r in rows)


def views_without_security_invoker(engine: Engine) -> list[str]:
    sql = text(
        """
        SELECT c.relname FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('v','m')
          AND NOT COALESCE('security_invoker=true' = ANY (c.reloptions), false)
        """
    )
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(sql)]


def test_all_views_are_security_invoker(owner_engine: Engine) -> None:
    assert views_without_security_invoker(owner_engine) == []


def test_view_introspection_detects_a_view_without_security_invoker(owner_engine: Engine) -> None:
    """Negative control so the guard above cannot pass vacuously by being broken."""
    with owner_engine.connect() as conn:
        conn.execute(text("CREATE VIEW zz_plain_view AS SELECT 1 AS x"))
    try:
        assert "zz_plain_view" in views_without_security_invoker(owner_engine)
    finally:
        with owner_engine.connect() as conn:
            conn.execute(text("DROP VIEW zz_plain_view"))


def test_updated_at_trigger_exists_on_every_table_with_updated_at(owner_engine: Engine) -> None:
    sql = text(
        """
        SELECT c.relname,
               EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                        WHERE t.tgrelid = c.oid AND p.proname = 'trg_set_updated_at'
                          AND (t.tgtype & 2) = 2 AND (t.tgtype & 16) = 16) AS has_trigger
        FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
          AND c.relname = ANY (:tables)
        """
    )
    with owner_engine.connect() as conn:
        rows = conn.execute(sql, {"tables": sorted(tenant_tables(owner_engine))}).all()
    assert rows
    assert [r[0] for r in rows if not r[1]] == []
