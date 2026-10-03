"""DATA_MODEL 0.5: suppliers are denied by default; only the documented P01 tables opt in.

INV-SUP-09, INV-PLT-22. Every statement runs as `qualloop_app` with actor_type = 'supplier_session'."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg.errors
import pytest
from sqlalchemy import Connection, Engine, text

from tests.factories.db import create_plant, create_tenant, tenant_conn
from tests.factories.dberr import expect_db_error
from tests.factories.rows import INSERTERS

pytestmark = pytest.mark.integration

SUPPLIER = "supplier_session"
RLS = "row-level security"
DEFAULT_DENY = ["plants", "users", "job_dead_letters"]


@pytest.mark.parametrize("table", DEFAULT_DENY)
def test_supplier_session_reads_nothing_from_default_deny_tables(
    app_engine: Engine, table: str
) -> None:
    tenant = create_tenant(app_engine)
    with tenant_conn(app_engine, tenant) as conn:
        INSERTERS[table](conn, tenant)
    with tenant_conn(app_engine, tenant, actor_type="user") as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1
    with tenant_conn(app_engine, tenant, actor_type=SUPPLIER) as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


@pytest.mark.parametrize("table", DEFAULT_DENY)
def test_supplier_session_cannot_insert_into_default_deny_tables(
    app_engine: Engine, table: str
) -> None:
    tenant = create_tenant(app_engine)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, tenant, actor_type=SUPPLIER) as conn,
    ):
        INSERTERS[table](conn, tenant)


def test_supplier_session_cannot_update_plants(app_engine: Engine) -> None:
    tenant = create_tenant(app_engine)
    create_plant(app_engine, tenant)
    with tenant_conn(app_engine, tenant, actor_type=SUPPLIER) as conn:
        assert conn.execute(text("UPDATE plants SET name = 'hacked'")).rowcount == 0
    with tenant_conn(app_engine, tenant) as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM plants WHERE name = 'hacked'")).scalar_one()
            == 0
        )


@pytest.mark.parametrize("table", ["activity_log", "outbox_events"])
def test_supplier_can_append_but_never_read_audit_and_outbox_rows(
    app_engine: Engine, table: str
) -> None:
    tenant = create_tenant(app_engine)
    contact = uuid4()
    with tenant_conn(app_engine, tenant, actor_type=SUPPLIER, actor_id=contact) as conn:
        if table == "activity_log":
            conn.execute(
                text(
                    "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type, "
                    "actor_id, session_id) VALUES (:t, 'scar', :o, 'supplier.submit', 'supplier_session', "
                    ":c, :s)"
                ),
                {"t": tenant, "o": uuid4(), "c": contact, "s": uuid4()},
            )
        else:
            INSERTERS[table](conn, tenant)
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    with tenant_conn(app_engine, tenant) as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1


@pytest.mark.parametrize("table", ["activity_log", "outbox_events"])
def test_supplier_insert_returning_fails_which_is_why_writers_never_use_returning(
    app_engine: Engine, table: str
) -> None:
    tenant = create_tenant(app_engine)
    contact = uuid4()
    sql = {
        "activity_log": (
            "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type, actor_id, "
            "session_id) VALUES (:t, 'scar', :o, 'x', 'supplier_session', :c, :s) RETURNING id"
        ),
        "outbox_events": (
            "INSERT INTO outbox_events (tenant_id, event_id, aggregate_type, aggregate_id, event_type, "
            "payload) VALUES (:t, :e, 'scar', :o, 'SCAR_RESPONSE_RECEIVED', '{}'::jsonb) RETURNING id"
        ),
    }[table]
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, tenant, actor_type=SUPPLIER, actor_id=contact) as conn,
    ):
        conn.execute(
            text(sql), {"t": tenant, "o": uuid4(), "c": contact, "s": uuid4(), "e": uuid4()}
        )


@pytest.mark.parametrize("table", ["activity_log", "outbox_events"])
def test_supplier_cannot_append_for_another_tenant(app_engine: Engine, table: str) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, a, actor_type=SUPPLIER, actor_id=uuid4()) as conn,
    ):
        INSERTERS[table](conn, b)


def test_supplier_sees_only_its_own_tenant_row_and_cannot_insert_tenants(
    app_engine: Engine,
) -> None:
    a, b = (
        create_tenant(app_engine, name="Customer A"),
        create_tenant(app_engine, name="Customer B"),
    )
    with tenant_conn(app_engine, a, actor_type=SUPPLIER) as conn:
        rows = conn.execute(text("SELECT id, name FROM tenants")).all()
    assert [(r[0], r[1]) for r in rows] == [(a, "Customer A")]
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, a, actor_type=SUPPLIER) as conn,
    ):
        INSERTERS["tenants"](conn, b)
    with tenant_conn(app_engine, a, actor_type=SUPPLIER) as conn:
        assert conn.execute(text("UPDATE tenants SET name = 'x'")).rowcount == 0


def _idem(conn: Connection, tenant: UUID, actor: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO idempotency_keys (tenant_id, actor_id, key, endpoint, request_hash, expires_at) "
            "VALUES (:t, :a, :k, 'POST /supplier/scar/response/submit', 'h', :x)"
        ),
        {"t": tenant, "a": actor, "k": str(uuid4()), "x": datetime.now(UTC) + timedelta(hours=24)},
    )


def test_supplier_idempotency_keys_are_visible_and_writable_only_for_its_own_actor(
    app_engine: Engine,
) -> None:
    tenant = create_tenant(app_engine)
    mine, other = uuid4(), uuid4()
    with tenant_conn(app_engine, tenant, actor_type="user") as conn:
        _idem(conn, tenant, other)
    with tenant_conn(app_engine, tenant, actor_type=SUPPLIER, actor_id=mine) as conn:
        _idem(conn, tenant, mine)
        actors = {r[0] for r in conn.execute(text("SELECT actor_id FROM idempotency_keys"))}
        assert actors == {mine}
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, tenant, actor_type=SUPPLIER, actor_id=mine) as conn,
    ):
        _idem(conn, tenant, other)


def test_supplier_cannot_delete_idempotency_keys_even_though_the_app_role_may(
    app_engine: Engine,
) -> None:
    tenant = create_tenant(app_engine)
    mine = uuid4()
    with tenant_conn(app_engine, tenant, actor_type=SUPPLIER, actor_id=mine) as conn:
        _idem(conn, tenant, mine)
    with tenant_conn(app_engine, tenant, actor_type=SUPPLIER, actor_id=mine) as conn:
        assert conn.execute(text("DELETE FROM idempotency_keys")).rowcount == 0
    with tenant_conn(app_engine, tenant, actor_type="system") as conn:
        assert conn.execute(text("DELETE FROM idempotency_keys")).rowcount == 1


def test_supplier_actor_type_value_consistent(app_engine: Engine) -> None:
    """INV-PLT-22: one value, 'supplier_session', in the GUC and in activity_log.actor_type."""
    tenant = create_tenant(app_engine)
    for value, expected in [
        ("supplier_session", True),
        ("supplier", False),
        ("user", False),
        ("system", False),
        ("ai", False),
    ]:
        with tenant_conn(app_engine, tenant, actor_type=value) as conn:
            assert conn.execute(text("SELECT app_is_supplier()")).scalar_one() is expected, value
    with (
        expect_db_error(psycopg.errors.CheckViolation),
        tenant_conn(app_engine, tenant) as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type, "
                "actor_id, session_id) VALUES (:t, 'scar', :o, 'x', 'supplier', :a, :s)"
            ),
            {"t": tenant, "o": uuid4(), "a": uuid4(), "s": uuid4()},
        )
    with tenant_conn(
        app_engine, tenant, actor_type=SUPPLIER
    ) as conn:  # the right value is accepted
        conn.execute(
            text(
                "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type, "
                "actor_id, session_id) VALUES (:t, 'scar', :o, 'x', 'supplier_session', :a, :s)"
            ),
            {"t": tenant, "o": uuid4(), "a": uuid4(), "s": uuid4()},
        )


def test_supplier_rls_denies_unlisted_tables_db(owner_engine: Engine, app_engine: Engine) -> None:
    """INV-SUP-09: for every table outside the opt-in list, a supplier sees zero rows and cannot write."""
    from tests.integration.db.test_schema_conventions import P01_SUPPLIER_SCOPED, tenant_tables

    tenant = create_tenant(app_engine)
    for table in sorted(tenant_tables(owner_engine) - P01_SUPPLIER_SCOPED):
        with tenant_conn(app_engine, tenant, actor_type=SUPPLIER) as conn:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
