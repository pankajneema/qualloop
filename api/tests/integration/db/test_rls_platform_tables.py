"""INV-PLT-01 / INV-PLT-02 on the real platform tables, as `qualloop_app` (never owner/superuser)."""

from uuid import UUID, uuid4

import psycopg.errors
import pytest
from sqlalchemy import Engine, create_engine, event, text

from app.core.config import Settings
from tests.conftest import _role_guard, assert_current_user
from tests.factories.db import create_plant, create_tenant, tenant_conn
from tests.factories.dberr import expect_db_error
from tests.factories.rows import INSERTERS, TABLES, TENANT_ROW_TABLE

pytestmark = pytest.mark.integration

RLS = "row-level security"


def _two_tenants_with_rows(engine: Engine, table: str) -> tuple[UUID, UUID]:
    a, b = create_tenant(engine), create_tenant(engine)
    if table != TENANT_ROW_TABLE:
        for tenant in (a, b):
            with tenant_conn(engine, tenant) as conn:
                INSERTERS[table](conn, tenant)
    return a, b


def test_test_connections_are_the_app_role(app_engine: Engine) -> None:
    assert_current_user(app_engine, "qualloop_app")


@pytest.mark.parametrize("table", TABLES)
def test_tenant_a_cannot_read_tenant_b_rows_raw_session(app_engine: Engine, table: str) -> None:
    a, b = _two_tenants_with_rows(app_engine, table)
    with tenant_conn(app_engine, a) as conn:
        visible = set(conn.execute(text(f"SELECT tenant_id FROM {table}")).scalars())
        by_id = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :b"), {"b": b}
        ).scalar_one()
    assert visible == {a}
    assert by_id == 0


@pytest.mark.parametrize("table", TABLES)
def test_tenant_a_cannot_insert_row_for_tenant_b(app_engine: Engine, table: str) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, a) as conn,
    ):
        INSERTERS[table](conn, b)


# P02 adds suppliers, parts and customers (all carry a `name` column that a hijack would overwrite).
@pytest.mark.parametrize(
    "table", ["plants", "users", "idempotency_keys", "tenants", "suppliers", "parts", "customers"]
)
def test_tenant_a_cannot_update_tenant_b_rows(app_engine: Engine, table: str) -> None:
    a, b = _two_tenants_with_rows(app_engine, table)
    column, value = (
        ("response_status", "418") if table == "idempotency_keys" else ("name", "'hijacked'")
    )
    with tenant_conn(app_engine, a) as conn:
        count = conn.execute(
            text(f"UPDATE {table} SET {column} = {value} WHERE tenant_id = :b"), {"b": b}
        ).rowcount
    assert count == 0
    with tenant_conn(app_engine, b) as conn:
        assert (
            conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = {value}")
            ).scalar_one()
            == 0
        )


def test_tenant_a_cannot_move_a_row_to_tenant_b_by_updating_tenant_id(app_engine: Engine) -> None:
    a, b = create_tenant(app_engine), create_tenant(app_engine)
    create_plant(app_engine, a)
    # tenant_id is not an updatable column: "permission denied" is a stronger refusal than the RLS check
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, f"({RLS})|permission denied"),
        tenant_conn(app_engine, a) as conn,
    ):
        conn.execute(text("UPDATE plants SET tenant_id = :b"), {"b": b})
    with tenant_conn(app_engine, b) as conn:
        assert conn.execute(text("SELECT count(*) FROM plants")).scalar_one() == 0


@pytest.mark.parametrize("table", TABLES)
def test_no_tenant_context_returns_zero_rows(app_engine: Engine, table: str) -> None:
    a, _ = _two_tenants_with_rows(app_engine, table)
    with tenant_conn(app_engine, None) as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    with tenant_conn(app_engine, a) as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() >= 1


@pytest.mark.parametrize("table", TABLES)
def test_no_tenant_context_insert_rejected(app_engine: Engine, table: str) -> None:
    a = create_tenant(app_engine)
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, RLS),
        tenant_conn(app_engine, None) as conn,
    ):
        INSERTERS[table](conn, a)


@pytest.mark.parametrize("table", TABLES)
def test_empty_string_tenant_context_behaves_like_unset(app_engine: Engine, table: str) -> None:
    """A reset GUC reads as '' (not NULL) on a reused connection; it must still fail closed."""
    _two_tenants_with_rows(app_engine, table)
    with app_engine.connect() as conn, conn.begin():
        conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        conn.execute(text("SELECT set_config('app.actor_type', 'user', true)"))
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_malformed_tenant_context_fails_closed(app_engine: Engine) -> None:
    create_tenant(app_engine)
    with app_engine.connect() as conn:
        outcome: int | None
        try:
            with conn.begin():
                conn.execute(text("SELECT set_config('app.tenant_id', 'not-a-uuid', true)"))
                outcome = conn.execute(text("SELECT count(*) FROM plants")).scalar_one()
        except Exception as exc:
            outcome = None
            assert "uuid" in str(exc).lower()
    assert outcome in (None, 0)


def test_tenant_guc_does_not_leak_into_the_next_transaction_on_a_reused_connection(
    settings: Settings, app_engine: Engine
) -> None:
    a = create_tenant(app_engine)
    create_plant(app_engine, a)
    one_conn = create_engine(settings.test_database_url, pool_size=1, max_overflow=0)
    event.listen(one_conn, "connect", _role_guard("qualloop_app"))
    try:
        with one_conn.connect() as conn, conn.begin():
            pid_1 = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a)})
            conn.execute(text("SELECT set_config('app.actor_type', 'user', true)"))
            assert conn.execute(text("SELECT count(*) FROM plants")).scalar_one() == 1
        with one_conn.connect() as conn, conn.begin():
            pid_2 = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
            leaked = conn.execute(
                text("SELECT current_setting('app.tenant_id', true)")
            ).scalar_one()
            assert conn.execute(text("SELECT count(*) FROM plants")).scalar_one() == 0
        assert pid_1 == pid_2, "the pool did not reuse the connection; the test proves nothing"
        assert leaked in (None, "")
    finally:
        one_conn.dispose()


def test_tenant_guc_does_not_survive_a_rolled_back_transaction(
    settings: Settings, app_engine: Engine
) -> None:
    one_conn = create_engine(settings.test_database_url, pool_size=1, max_overflow=0)
    event.listen(one_conn, "connect", _role_guard("qualloop_app"))
    try:
        with one_conn.connect() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(uuid4())})
            conn.rollback()
        with one_conn.connect() as conn:
            assert conn.execute(
                text("SELECT current_setting('app.tenant_id', true)")
            ).scalar_one() in (
                None,
                "",
            )
    finally:
        one_conn.dispose()


def test_composite_fk_rejects_cross_tenant_reference(
    app_engine: Engine,
) -> None:
    """tenant_id REFERENCES tenants(id): a row cannot claim a tenant that does not exist, even when the
    RLS predicate is satisfied (GUC set to that same non-existent id)."""
    ghost = uuid4()
    with (
        expect_db_error(psycopg.errors.ForeignKeyViolation),
        tenant_conn(app_engine, ghost) as conn,
    ):
        INSERTERS["plants"](conn, ghost)
