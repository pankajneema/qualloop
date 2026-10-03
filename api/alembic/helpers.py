"""Reusable migration helpers (ADR-004, DATA_MODEL section 0).

Used by every table-creating migration from P01 (`from helpers import ...`):
  std_columns() / std_constraints()  - the STD columns (section 0.2)
  enable_tenant_rls(table)           - ENABLE + FORCE RLS, tenant policy T, and the default-deny
                                       RESTRICTIVE policy p_supplier_deny for supplier sessions
  enable_supplier_scoped_rls(...)    - replaces p_supplier_deny with explicit per-command policies
                                       for the few tables a supplier session may touch
  add_updated_at_trigger(table)      - trg_set_updated_at
  data_migration_per_tenant(...)     - RLS-safe data migrations (DATA_MODEL 0.9)
  append_only(table)                 - trg_append_only + revoke UPDATE/DELETE/TRUNCATE from qualloop_app

Supplier sessions are identified by the GUC app.actor_type = 'supplier_session'. Every tenant table is
invisible to them unless a migration opts in explicitly.
"""

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import op

APP_ROLE = "qualloop_app"
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def std_columns(*, tenant_fk: bool = True) -> list[sa.Column[Any]]:
    """STD columns. `id` has no server default: the app generates UUIDv7 (ADR-005)."""
    tenant_col: sa.Column[Any] = (
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
        )
        if tenant_fk
        else sa.Column("tenant_id", sa.UUID(), nullable=False)
    )
    return [
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("app_uuid_v7()")),
        tenant_col,
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.UUID(), nullable=True),
    ]


def std_constraints(table: str) -> list[sa.UniqueConstraint]:
    """UNIQUE (tenant_id, id): target of composite FKs (section 0.3)."""
    return [sa.UniqueConstraint("tenant_id", "id", name=f"{_ident(table)}_tenant_id_id_key")]


SUPPLIER_ACTOR = "supplier_session"
_NOT_SUPPLIER = f"app_current_actor_type() IS DISTINCT FROM '{SUPPLIER_ACTOR}'"


def enable_tenant_rls(table: str) -> None:
    """Policy T (tenant isolation) + deny-by-default for supplier sessions (p_supplier_deny)."""
    t = _ident(table)
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY p_tenant ON {t} AS PERMISSIVE FOR ALL TO {APP_ROLE} "
        f"USING (tenant_id = app_current_tenant_id()) "
        f"WITH CHECK (tenant_id = app_current_tenant_id())"
    )
    op.execute(
        f"CREATE POLICY p_supplier_deny ON {t} AS RESTRICTIVE FOR ALL TO {APP_ROLE} "
        f"USING ({_NOT_SUPPLIER}) WITH CHECK ({_NOT_SUPPLIER})"
    )


def enable_supplier_scoped_rls(
    table: str,
    select_predicate: str,
    insert: bool = False,
    update_predicate: str | None = None,
) -> None:
    """Opt a table in for supplier sessions. Call after enable_tenant_rls(table).

    Drops p_supplier_deny and creates per-command RESTRICTIVE policies:
      SELECT: non-supplier actors OR select_predicate (use 'false' for insert-only tables)
      INSERT: allowed for suppliers only when insert=True
      UPDATE: allowed for suppliers only on rows matching update_predicate (None = never)
      DELETE: never for suppliers
    Predicates are trusted SQL written in migrations, never user input.
    """
    t = _ident(table)
    op.execute(f"DROP POLICY p_supplier_deny ON {t}")
    op.execute(
        f"CREATE POLICY p_supplier_select ON {t} AS RESTRICTIVE FOR SELECT TO {APP_ROLE} "
        f"USING ({_NOT_SUPPLIER} OR ({select_predicate}))"
    )
    # insert=True: suppliers may insert rows matching the select predicate; for append-only tables
    # (select_predicate "false", e.g. activity_log) any row within the tenant is allowed.
    if insert:
        insert_check = (
            f"{_NOT_SUPPLIER} OR true"
            if select_predicate.strip().lower() == "false"
            else f"{_NOT_SUPPLIER} OR ({select_predicate})"
        )
    else:
        insert_check = _NOT_SUPPLIER
    op.execute(
        f"CREATE POLICY p_supplier_insert ON {t} AS RESTRICTIVE FOR INSERT TO {APP_ROLE} "
        f"WITH CHECK ({insert_check})"
    )
    update_expr = (
        _NOT_SUPPLIER if update_predicate is None else (f"{_NOT_SUPPLIER} OR ({update_predicate})")
    )
    op.execute(
        f"CREATE POLICY p_supplier_update ON {t} AS RESTRICTIVE FOR UPDATE TO {APP_ROLE} "
        f"USING ({update_expr}) WITH CHECK ({update_expr})"
    )
    op.execute(
        f"CREATE POLICY p_supplier_delete ON {t} AS RESTRICTIVE FOR DELETE TO {APP_ROLE} "
        f"USING ({_NOT_SUPPLIER})"
    )


def add_updated_at_trigger(table: str) -> None:
    t = _ident(table)
    op.execute(
        f"CREATE TRIGGER trg_{t}_set_updated_at BEFORE UPDATE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at()"
    )


def append_only(table: str) -> None:
    """Grants CR only plus a trigger that raises on UPDATE/DELETE (INV-PLT-05, INV-QTY-04, INV-SCO-08)."""
    t = _ident(table)
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM {APP_ROLE}")
    op.execute(
        f"CREATE TRIGGER trg_{t}_append_only BEFORE UPDATE OR DELETE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION trg_append_only()"
    )


def data_migration_per_tenant(
    revision: str,
    tenant_ids_sql: str,
    count_sql: str,
    step: Callable[[Connection], None],
    expected_after: Callable[[int], int],
    write_activity: Callable[[Connection, UUID, str], None] | None = None,
) -> dict[UUID, tuple[int, int]]:
    """Run a row-touching migration step safely under RLS (DATA_MODEL 0.9, ADR-004 item 9).

    1. SET LOCAL ROLE qualloop_app, so RLS applies (the owner sees no rows under FORCE RLS).
    2. For each tenant from `tenant_ids_sql` (P01+: "SELECT app_active_tenant_ids()"): one savepoint,
       set_config('app.tenant_id', ..., true) and app.actor_type = 'system'.
    3. count_sql (returns one integer) is evaluated before and after `step`; if the after-count differs
       from expected_after(before), raise: the whole migration aborts.
    4. write_activity(conn, tenant_id, 'migration.<revision>') records the audit row; supplied by the caller
       because activity_log arrives in P01 (SPEC dependency, not guessed here).
    Returns {tenant_id: (before, after)}. The role and GUCs are always reset, so later DDL runs as owner.
    """
    conn = op.get_bind()
    results: dict[UUID, tuple[int, int]] = {}
    conn.execute(sa.text(f"SET LOCAL ROLE {APP_ROLE}"))
    try:
        tenant_ids = [UUID(str(r[0])) for r in conn.execute(sa.text(tenant_ids_sql)).all()]
        for tenant_id in tenant_ids:
            with conn.begin_nested():
                conn.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                conn.execute(sa.text("SELECT set_config('app.actor_type', 'system', true)"))
                before = int(conn.execute(sa.text(count_sql)).scalar_one())
                step(conn)
                after = int(conn.execute(sa.text(count_sql)).scalar_one())
                expected = expected_after(before)
                if after != expected:
                    raise RuntimeError(
                        f"data migration {revision}: tenant {tenant_id} count {after} "
                        f"!= expected {expected} (before {before}); aborting"
                    )
                if write_activity is not None:
                    write_activity(conn, tenant_id, f"migration.{revision}")
                results[tenant_id] = (before, after)
            conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
            conn.execute(sa.text("SELECT set_config('app.actor_type', '', true)"))
    finally:
        conn.execute(sa.text("RESET ROLE"))
    return results
