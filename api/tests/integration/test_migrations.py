import pytest
from sqlalchemy import Engine, text

from alembic import command
from app.core.config import Settings
from tests.conftest import alembic_config
from tests.factories.env import owner_url

pytestmark = pytest.mark.integration

FUNCTIONS = {
    "app_current_tenant_id",
    "app_current_actor_type",
    "app_uuid_v7",
    "app_guc_uuid",
    "app_is_supplier",
    "trg_set_updated_at",
    "trg_append_only",
    "app_current_supplier_session_id",
    "app_current_magic_link_id",
    "app_current_scope_object_type",
    "app_current_scope_object_id",
    "app_current_supplier_id",
    "app_current_actor_id",
}


def _functions(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace")
        ).all()
    return {r[0] for r in rows}


def test_upgrade_downgrade_upgrade(settings: Settings, owner_engine: Engine) -> None:
    cfg = alembic_config(owner_url())
    command.upgrade(cfg, "head")
    assert _functions(owner_engine) >= FUNCTIONS

    command.downgrade(cfg, "base")
    assert not (FUNCTIONS & _functions(owner_engine))

    command.upgrade(cfg, "head")
    assert _functions(owner_engine) >= FUNCTIONS


def test_app_role_cannot_bypass_rls(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('qualloop_app','qualloop_owner','qualloop_sysfn')"
            )
        ).all()
    assert {r[0] for r in rows} == {"qualloop_app", "qualloop_owner", "qualloop_sysfn"}
    assert all(not r[1] and not r[2] for r in rows)


def test_uuid_v7_is_version_7_and_time_ordered(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        first, second = (
            str(conn.execute(text("SELECT app_uuid_v7()")).scalar_one()) for _ in range(2)
        )
    assert first[14] == "7" and second[14] == "7"
    assert first[19] in "89ab"
    assert first[:8] <= second[:8]
