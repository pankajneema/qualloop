"""INV-PLT-01 through a raw ORM session as qualloop_app (section 21.2): the ORM adds no filter of its own,
so any isolation here is the database's."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.factories.contract import load
from tests.factories.db import SeededTenant, create_plant, create_tenant

pytestmark = pytest.mark.integration


def _session(engine: Engine, tenant: UUID | None, actor: str = "user") -> Session:
    session = Session(engine)
    if tenant:
        session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
    session.execute(text("SELECT set_config('app.actor_type', :a, true)"), {"a": actor})
    return session


@pytest.fixture
def pair(app_engine: Engine) -> Iterator[tuple[SeededTenant, SeededTenant]]:
    from tests.factories.db import seed_tenant

    yield seed_tenant(app_engine), seed_tenant(app_engine)


def test_orm_select_returns_only_the_session_tenants_rows(
    app_engine: Engine, pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = pair
    plant_cls, user_cls = load("app.core.models", "Plant"), load("app.core.models", "User")
    with _session(app_engine, a.id) as session:
        plants = session.scalars(select(plant_cls)).all()
        users = session.scalars(select(user_cls)).all()
    assert {p.id for p in plants} == set(a.plants)
    assert {u.tenant_id for u in users} == {a.id}
    assert not {p.id for p in plants} & set(b.plants)


def test_orm_get_by_primary_key_of_a_foreign_row_returns_none(
    app_engine: Engine, pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = pair
    plant_cls = load("app.core.models", "Plant")
    with _session(app_engine, a.id) as session:
        assert session.get(plant_cls, b.plants[0]) is None


def test_orm_cannot_add_a_row_for_another_tenant(
    app_engine: Engine, pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = pair
    plant_cls = load("app.core.models", "Plant")
    with _session(app_engine, a.id) as session:
        session.add(plant_cls(id=uuid4(), tenant_id=b.id, name="Planted", code="EVIL1"))
        with pytest.raises(DBAPIError, match="row-level security"):
            session.flush()
        session.rollback()


def test_orm_update_of_a_foreign_row_affects_nothing(
    app_engine: Engine, pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = pair
    with _session(app_engine, a.id) as session:
        result = session.execute(
            text("UPDATE plants SET name = 'hijacked' WHERE id = :i"), {"i": b.plants[0]}
        )
        assert result.rowcount == 0  # type: ignore[attr-defined]
        session.commit()
    with _session(app_engine, b.id) as session:
        assert (
            session.execute(
                text("SELECT name FROM plants WHERE id = :i"), {"i": b.plants[0]}
            ).scalar_one()
            != "hijacked"
        )


def test_orm_session_without_tenant_context_sees_nothing(
    app_engine: Engine, pair: tuple[SeededTenant, SeededTenant]
) -> None:
    plant_cls = load("app.core.models", "Plant")
    with _session(app_engine, None) as session:
        assert session.scalars(select(plant_cls)).all() == []


def test_orm_session_cannot_delete_rows_at_all(app_engine: Engine) -> None:
    tenant = create_tenant(app_engine)
    plant = create_plant(app_engine, tenant)
    plant_cls = load("app.core.models", "Plant")
    with _session(app_engine, tenant) as session:
        obj = session.get(plant_cls, plant)
        assert obj is not None
        session.delete(obj)
        with pytest.raises(DBAPIError, match="permission denied"):
            session.flush()
        session.rollback()
