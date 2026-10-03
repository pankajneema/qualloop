"""Proves the baseline RLS templates (ADR-004) on throwaway tables made with the migration helpers."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration

TENANT_A = uuid4()
TENANT_B = uuid4()
SCOPE_1 = uuid4()
SCOPE_2 = uuid4()
T_DEFAULT = "zz_rls_probe"
T_INSERT_ONLY = "zz_rls_insert_only"
T_SCOPED = "zz_rls_scoped"
T_NAIVE = "zz_rls_naive"
ALL_PROBES = (T_DEFAULT, T_INSERT_ONLY, T_SCOPED, T_NAIVE)


def _create(owner_engine: Engine, table: str, rls: Callable[[], None] | None) -> None:
    with owner_engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {table} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                f"tenant_id uuid NOT NULL, scope_id uuid, note text NOT NULL)"
            )
        )
        # Seed before enabling RLS: FORCE applies to the owner too.
        conn.execute(
            text(
                f"INSERT INTO {table} (tenant_id, scope_id, note) VALUES "
                f"(:a, :s1, 'a1'), (:a, :s2, 'a2'), (:b, :s1, 'b1')"
            ),
            {"a": TENANT_A, "b": TENANT_B, "s1": SCOPE_1, "s2": SCOPE_2},
        )
        if rls:
            with Operations.context(MigrationContext.configure(conn)):
                rls()


@pytest.fixture(scope="module")
def probes(owner_engine: Engine) -> Iterator[None]:
    from helpers import enable_supplier_scoped_rls, enable_tenant_rls

    def drop() -> None:
        with owner_engine.connect() as conn:
            for t in ALL_PROBES:
                conn.execute(text(f"DROP TABLE IF EXISTS {t}"))

    drop()
    _create(owner_engine, T_DEFAULT, lambda: enable_tenant_rls(T_DEFAULT))

    def insert_only() -> None:
        enable_tenant_rls(T_INSERT_ONLY)
        enable_supplier_scoped_rls(T_INSERT_ONLY, select_predicate="false", insert=True)

    _create(owner_engine, T_INSERT_ONLY, insert_only)

    def scoped() -> None:
        enable_tenant_rls(T_SCOPED)
        enable_supplier_scoped_rls(
            T_SCOPED,
            select_predicate="scope_id = app_current_scope_object_id()",
            update_predicate="scope_id = app_current_scope_object_id()",
        )

    _create(owner_engine, T_SCOPED, scoped)

    _create(owner_engine, T_NAIVE, None)
    with owner_engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {T_NAIVE} ENABLE ROW LEVEL SECURITY"))
    yield
    drop()


@contextmanager
def _app_tx(
    engine: Engine,
    tenant: UUID | None,
    actor: str | None = None,
    scope: UUID | None = None,
) -> Iterator[Connection]:
    with engine.connect() as conn, conn.begin():
        for name, value in (
            ("app.tenant_id", tenant),
            ("app.actor_type", actor),
            ("app.scope_object_id", scope),
        ):
            if value is not None:
                conn.execute(text("SELECT set_config(:n, :v, true)"), {"n": name, "v": str(value)})
        yield conn


def _count(conn: Connection, table: str) -> int:
    return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


RLS_ERR = "row-level security"


def test_app_role_is_not_superuser_and_does_not_bypass(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert conn.execute(text("SELECT current_user")).scalar_one() == "qualloop_app"
    assert tuple(row) == (False, False)


def test_app_role_has_no_temp_privilege(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        has_temp = conn.execute(
            text("SELECT has_database_privilege(current_user, current_database(), 'TEMP')")
        ).scalar_one()
        assert has_temp is False
        with pytest.raises(DBAPIError, match="permission denied"):
            conn.execute(text("CREATE TEMP TABLE zz_tmp (x int)"))


def test_rls_is_forced_on_probe_table(owner_engine: Engine, probes: None) -> None:
    with owner_engine.connect() as conn:
        row = conn.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
            {"t": T_DEFAULT},
        ).one()
    assert tuple(row) == (True, True)


def test_tenant_a_sees_only_own_rows(app_engine: Engine, probes: None) -> None:
    with _app_tx(app_engine, TENANT_A) as conn:
        notes = {r[0] for r in conn.execute(text(f"SELECT note FROM {T_DEFAULT}"))}
    assert notes == {"a1", "a2"}


def test_tenant_b_rows_invisible_to_a_even_by_id(app_engine: Engine, probes: None) -> None:
    with _app_tx(app_engine, TENANT_A) as conn:
        n = conn.execute(
            text(f"SELECT count(*) FROM {T_DEFAULT} WHERE tenant_id = :b"), {"b": TENANT_B}
        ).scalar_one()
    assert n == 0


def test_insert_for_other_tenant_fails(app_engine: Engine, probes: None) -> None:
    with pytest.raises(DBAPIError, match=RLS_ERR), _app_tx(app_engine, TENANT_A) as conn:
        conn.execute(
            text(f"INSERT INTO {T_DEFAULT} (tenant_id, note) VALUES (:b, 'evil')"), {"b": TENANT_B}
        )


def test_update_cannot_move_row_to_other_tenant(app_engine: Engine, probes: None) -> None:
    with pytest.raises(DBAPIError, match=RLS_ERR), _app_tx(app_engine, TENANT_A) as conn:
        conn.execute(
            text(f"UPDATE {T_DEFAULT} SET tenant_id = :b WHERE note = 'a1'"), {"b": TENANT_B}
        )


def test_no_tenant_set_sees_nothing_and_cannot_insert(app_engine: Engine, probes: None) -> None:
    with _app_tx(app_engine, None) as conn:
        assert _count(conn, T_DEFAULT) == 0
    with pytest.raises(DBAPIError, match=RLS_ERR), _app_tx(app_engine, None) as conn:
        conn.execute(
            text(f"INSERT INTO {T_DEFAULT} (tenant_id, note) VALUES (:a, 'x')"), {"a": TENANT_A}
        )


def test_app_role_has_no_delete(app_engine: Engine, probes: None) -> None:
    with (
        pytest.raises(DBAPIError, match="permission denied"),
        _app_tx(app_engine, TENANT_A) as conn,
    ):
        conn.execute(text(f"DELETE FROM {T_DEFAULT}"))


# (a) default table: supplier session is denied everything
def test_default_table_denies_supplier_select_insert_update(
    app_engine: Engine, probes: None
) -> None:
    with _app_tx(app_engine, TENANT_A, actor="supplier_session") as conn:
        assert _count(conn, T_DEFAULT) == 0
    with _app_tx(app_engine, TENANT_A, actor="user") as conn:
        assert _count(conn, T_DEFAULT) == 2
    with (
        pytest.raises(DBAPIError, match=RLS_ERR),
        _app_tx(app_engine, TENANT_A, actor="supplier_session") as conn,
    ):
        conn.execute(
            text(f"INSERT INTO {T_DEFAULT} (tenant_id, note) VALUES (:a, 'x')"), {"a": TENANT_A}
        )
    with _app_tx(app_engine, TENANT_A, actor="supplier_session") as conn:
        updated = conn.execute(text(f"UPDATE {T_DEFAULT} SET note = 'hacked'")).rowcount
    assert updated == 0


# (b) insert-only table (activity_log style)
def test_insert_only_table_supplier_can_insert_but_not_read(
    app_engine: Engine, probes: None
) -> None:
    with _app_tx(app_engine, TENANT_A, actor="supplier_session") as conn:
        conn.execute(
            text(f"INSERT INTO {T_INSERT_ONLY} (tenant_id, note) VALUES (:a, 'logged')"),
            {"a": TENANT_A},
        )
        assert _count(conn, T_INSERT_ONLY) == 0
        assert conn.execute(text(f"UPDATE {T_INSERT_ONLY} SET note = 'x'")).rowcount == 0
    with _app_tx(app_engine, TENANT_A, actor="user") as conn:
        assert _count(conn, T_INSERT_ONLY) == 3  # a1, a2, logged
    # still tenant-scoped for suppliers
    with (
        pytest.raises(DBAPIError, match=RLS_ERR),
        _app_tx(app_engine, TENANT_A, actor="supplier_session") as conn,
    ):
        conn.execute(
            text(f"INSERT INTO {T_INSERT_ONLY} (tenant_id, note) VALUES (:b, 'x')"), {"b": TENANT_B}
        )


# (c) predicate-scoped table
def test_scoped_table_supplier_sees_only_scope_rows(app_engine: Engine, probes: None) -> None:
    with _app_tx(app_engine, TENANT_A, actor="supplier_session", scope=SCOPE_1) as conn:
        notes = {r[0] for r in conn.execute(text(f"SELECT note FROM {T_SCOPED}"))}
        assert notes == {"a1"}  # b1 has the same scope but another tenant
        assert conn.execute(text(f"UPDATE {T_SCOPED} SET note = 'edited'")).rowcount == 1
    with _app_tx(app_engine, TENANT_A, actor="supplier_session") as conn:  # no scope set
        assert _count(conn, T_SCOPED) == 0
    with _app_tx(app_engine, TENANT_A, actor="user") as conn:
        assert _count(conn, T_SCOPED) == 2
    with (
        pytest.raises(DBAPIError, match=RLS_ERR),
        _app_tx(app_engine, TENANT_A, actor="supplier_session", scope=SCOPE_1) as conn,
    ):
        conn.execute(
            text(f"INSERT INTO {T_SCOPED} (tenant_id, note) VALUES (:a, 'x')"), {"a": TENANT_A}
        )


def tables_missing_supplier_policy(engine: Engine) -> set[str]:
    """RLS tables in public with neither p_supplier_deny nor the full scoped policy set."""
    sql = text(
        """
        SELECT c.relname,
               array_agg(p.polname) FILTER (WHERE p.polname IS NOT NULL) AS policies
        FROM pg_class c
        LEFT JOIN pg_policy p ON p.polrelid = c.oid
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.relrowsecurity
        GROUP BY c.relname
        """
    )
    scoped = {"p_supplier_select", "p_supplier_insert", "p_supplier_update", "p_supplier_delete"}
    missing = set()
    with engine.connect() as conn:
        for name, policies in conn.execute(sql):
            have = set(policies or [])
            if "p_supplier_deny" not in have and not scoped <= have:
                missing.add(name)
    return missing


def test_every_rls_table_has_supplier_policy(owner_engine: Engine, probes: None) -> None:
    # Wired for P01+: every real table must pass. The deliberately naive probe is the only offender.
    assert tables_missing_supplier_policy(owner_engine) - {T_NAIVE} == set()


def test_introspection_detects_table_without_supplier_policy(
    owner_engine: Engine, probes: None
) -> None:
    assert T_NAIVE in tables_missing_supplier_policy(owner_engine)


def test_guc_accessors_null_when_unset_and_parse_when_set(app_engine: Engine) -> None:
    fns = [
        "app_current_supplier_session_id",
        "app_current_magic_link_id",
        "app_current_scope_object_type",
        "app_current_scope_object_id",
        "app_current_supplier_id",
        "app_current_actor_id",
    ]
    with app_engine.connect() as conn:
        for fn in fns:
            assert conn.execute(text(f"SELECT {fn}()")).scalar_one() is None
    sid = uuid4()
    with app_engine.connect() as conn, conn.begin():
        conn.execute(text("SELECT set_config('app.supplier_id', :v, true)"), {"v": str(sid)})
        conn.execute(text("SELECT set_config('app.scope_object_type', 'scar', true)"))
        assert conn.execute(text("SELECT app_current_supplier_id()")).scalar_one() == sid
        assert conn.execute(text("SELECT app_current_scope_object_type()")).scalar_one() == "scar"


T_MIGRATE = "zz_rls_datamig"


@pytest.fixture
def datamig_table(owner_engine: Engine, app_engine: Engine, probes: None) -> Iterator[None]:
    from helpers import enable_tenant_rls

    with owner_engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {T_MIGRATE}"))
        conn.execute(
            text(
                f"CREATE TABLE {T_MIGRATE} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                f"tenant_id uuid NOT NULL, note text NOT NULL, actor text)"
            )
        )
        with Operations.context(MigrationContext.configure(conn)):
            enable_tenant_rls(T_MIGRATE)
    for tenant, notes in ((TENANT_A, ["a1", "a2"]), (TENANT_B, ["b1"])):
        with _app_tx(app_engine, tenant, actor="user") as c:
            for n in notes:
                c.execute(
                    text(f"INSERT INTO {T_MIGRATE} (tenant_id, note) VALUES (:t, :n)"),
                    {"t": tenant, "n": n},
                )
    yield
    with owner_engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {T_MIGRATE}"))


def _run_datamig(
    engine: Engine, expected_after: Callable[[int], int], seen: list[tuple[UUID, str]]
) -> dict[UUID, tuple[int, int]]:
    from helpers import data_migration_per_tenant

    def step(conn: Connection) -> None:
        conn.execute(
            text(f"UPDATE {T_MIGRATE} SET note = 'migrated', actor = app_current_actor_type()")
        )

    def activity(conn: Connection, tenant: UUID, action: str) -> None:
        seen.append((tenant, action))

    # Real owner connection inside a transaction, like Alembic's migration transaction.
    transactional = engine.execution_options(isolation_level="READ COMMITTED")
    with transactional.connect() as conn, conn.begin():
        with Operations.context(MigrationContext.configure(conn)):
            result = data_migration_per_tenant(
                "0042",
                tenant_ids_sql=f"SELECT * FROM (VALUES ('{TENANT_A}'::uuid), ('{TENANT_B}'::uuid)) v(id)",
                count_sql=f"SELECT count(*) FROM {T_MIGRATE} WHERE note <> 'migrated'",
                step=step,
                expected_after=expected_after,
                write_activity=activity,
            )
        assert conn.execute(text("SELECT current_user")).scalar_one() == "qualloop_owner"
        assert conn.execute(text("SELECT app_current_tenant_id()")).scalar_one() is None
    return result


def test_data_migration_sets_tenant_guc_and_asserts_counts(
    owner_engine: Engine, app_engine: Engine, datamig_table: None
) -> None:
    seen: list[tuple[UUID, str]] = []
    result = _run_datamig(owner_engine, lambda before: 0, seen)
    assert result == {TENANT_A: (2, 0), TENANT_B: (1, 0)}  # each tenant counted only its own rows
    assert seen == [(TENANT_A, "migration.0042"), (TENANT_B, "migration.0042")]
    with _app_tx(app_engine, TENANT_A, actor="user") as conn:
        rows = conn.execute(text(f"SELECT note, actor FROM {T_MIGRATE}")).all()
    assert {tuple(r) for r in rows} == {("migrated", "system")}


def test_data_migration_aborts_when_counts_differ(
    owner_engine: Engine, app_engine: Engine, datamig_table: None
) -> None:
    with pytest.raises(RuntimeError, match="aborting"):
        _run_datamig(owner_engine, lambda before: before, [])
    with _app_tx(app_engine, TENANT_A, actor="user") as conn:  # rolled back
        notes = {r[0] for r in conn.execute(text(f"SELECT note FROM {T_MIGRATE}"))}
    assert notes == {"a1", "a2"}
