"""INV-PLT-16: migrations are reversible (up, down, up) and the platform revision is clean on its own."""

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from alembic import command
from app.core.config import Settings
from tests.conftest import alembic_config
from tests.factories.db import create_plant, create_tenant
from tests.factories.env import owner_url
from tests.integration.db.test_definer_functions import (
    P01_DEFINER_FUNCTIONS,
    SAFE_SEARCH_PATH,
    _definers,
)
from tests.integration.db.test_schema_conventions import P01_TABLES, tenant_tables

pytestmark = pytest.mark.integration

BASELINE_FUNCTIONS = {
    "app_current_tenant_id",
    "app_uuid_v7",
    "trg_set_updated_at",
    "trg_append_only",
}


def _table_names(engine: Engine) -> set[str]:
    return tenant_tables(engine, require_p01=False)


def _function_names(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace")
            )
        }


def test_migration_chain_has_one_head_and_the_platform_revision_follows_the_baseline(
    settings: Settings,
) -> None:
    script = ScriptDirectory.from_config(alembic_config(owner_url()))
    heads = script.get_heads()
    assert len(heads) == 1
    head = script.get_revision(heads[0])
    assert head is not None and head.revision != "0001"
    assert head.down_revision == "0001"


def test_migrations_up_down_up(
    settings: Settings, owner_engine: Engine, app_engine: Engine
) -> None:
    cfg = alembic_config(owner_url())
    command.upgrade(cfg, "head")
    assert _table_names(owner_engine) >= P01_TABLES
    assert _function_names(owner_engine) >= P01_DEFINER_FUNCTIONS | BASELINE_FUNCTIONS

    command.downgrade(cfg, "base")
    assert _table_names(owner_engine) == set()
    assert not (_function_names(owner_engine) & (P01_DEFINER_FUNCTIONS | BASELINE_FUNCTIONS))
    with owner_engine.connect() as conn:  # cluster-level roles must survive a downgrade
        roles = {
            r[0]
            for r in conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname LIKE 'qualloop\\_%'")
            )
        }
    assert {"qualloop_owner", "qualloop_app", "qualloop_sysfn"} <= roles

    command.upgrade(cfg, "head")
    assert _table_names(owner_engine) >= P01_TABLES
    definers = {d[0]: d for d in _definers(owner_engine)}
    assert set(definers) == P01_DEFINER_FUNCTIONS
    assert all(SAFE_SEARCH_PATH in (d[3] or []) for d in definers.values())


def test_after_a_round_trip_rls_is_forced_and_the_app_role_still_works(
    settings: Settings, owner_engine: Engine, app_engine: Engine
) -> None:
    cfg = alembic_config(owner_url())
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with owner_engine.connect() as conn:
        unforced = conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                "AND relkind = 'r' AND relname <> 'alembic_version' AND relname NOT LIKE 'zz\\_%' "
                "AND NOT (relrowsecurity AND relforcerowsecurity)"
            )
        ).all()
    assert unforced == []
    tenant = create_tenant(app_engine)
    create_plant(app_engine, tenant)  # smoke: insert + RLS + grants work after the round trip


def test_downgrade_one_step_removes_only_the_platform_objects(
    settings: Settings, owner_engine: Engine
) -> None:
    cfg = alembic_config(owner_url())
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    try:
        assert _table_names(owner_engine) == set()
        assert not (_function_names(owner_engine) & P01_DEFINER_FUNCTIONS)
        assert _function_names(owner_engine) >= BASELINE_FUNCTIONS
    finally:
        command.upgrade(cfg, "head")
    assert _table_names(owner_engine) >= P01_TABLES
