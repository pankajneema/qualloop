"""A-98 (P01): the last active admin of a tenant cannot be deactivated or demoted, whoever asks, and two admins
cannot demote or deactivate each other at the same moment. Inactive admins do not count."""

import threading
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.db import (
    SeededTenant,
    SeededUser,
    create_tenant,
    create_user,
    fetch_all,
    seed_tenant,
)
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration

ROUNDS = 6


def active_admins(engine: Engine, tenant: UUID) -> int:
    rows = fetch_all(
        engine, tenant, "SELECT count(*) AS n FROM users WHERE role = 'admin' AND active"
    )
    return int(rows[0]["n"])


def user_row(engine: Engine, tenant: UUID, user_id: UUID) -> dict[str, Any]:
    return fetch_all(
        engine, tenant, "SELECT role, active FROM users WHERE id = :i", {"i": user_id}
    )[0]


def demote(client: ApiClient, target: SeededUser) -> httpx.Response:
    return client.post(f"/users/{target.id}/update", {"role": "quality", "reason": "Stepping down"})


def deactivate(client: ApiClient, target: SeededUser) -> httpx.Response:
    return client.post(f"/users/{target.id}/deactivate", {"reason": "Left the company"})


def assert_refused_as_invariant(resp: httpx.Response) -> None:
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "invariant_violation"


# --- the only active admin --------------------------------------------------------------------------
def test_deactivating_the_only_active_admin_is_refused_with_invariant_violation(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    before = len(log_rows(app_engine, seeded.id, seeded.admin.id))
    assert_refused_as_invariant(deactivate(admin, seeded.admin))
    assert user_row(app_engine, seeded.id, seeded.admin.id)["active"] is True
    assert len(log_rows(app_engine, seeded.id, seeded.admin.id)) == before, (
        "a refused command audits nothing"
    )
    assert outbox_rows(app_engine, seeded.id, seeded.admin.id) == []
    assert admin.get("/me").status_code == 200, "the admin's session is untouched"


def test_demoting_the_only_active_admin_is_refused_with_invariant_violation(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    assert_refused_as_invariant(demote(api.login_as(seeded.admin), seeded.admin))
    assert user_row(app_engine, seeded.id, seeded.admin.id)["role"] == "admin"
    assert active_admins(app_engine, seeded.id) == 1


def test_an_inactive_admin_does_not_count_as_a_second_admin(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    create_user(app_engine, seeded.id, role="admin", active=False)
    admin = api.login_as(seeded.admin)
    assert_refused_as_invariant(demote(admin, seeded.admin))
    assert_refused_as_invariant(deactivate(admin, seeded.admin))
    assert active_admins(app_engine, seeded.id) == 1


def test_the_only_active_admin_may_still_change_name_mobile_and_plants(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    resp = api.login_as(seeded.admin).post(
        f"/users/{seeded.admin.id}/update", {"name": "Renamed Admin", "mobile": "+919876500001"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "admin"


def test_the_guard_counts_admins_per_tenant_not_across_tenants(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    """An admin in ANOTHER company is not a second admin here."""
    assert seeded.admin
    create_user(app_engine, create_tenant(app_engine), role="admin")
    assert_refused_as_invariant(deactivate(api.login_as(seeded.admin), seeded.admin))


# --- with another active admin ----------------------------------------------------------------------
def test_an_admin_can_be_demoted_when_another_active_admin_exists(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    second = create_user(app_engine, seeded.id, role="admin")
    resp = demote(api.login_as(second), seeded.admin)
    assert resp.status_code == 200, resp.text
    assert user_row(app_engine, seeded.id, seeded.admin.id)["role"] == "quality"
    assert active_admins(app_engine, seeded.id) == 1


def test_an_admin_can_be_deactivated_when_another_active_admin_exists(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    second = create_user(app_engine, seeded.id, role="admin")
    resp = deactivate(api.login_as(second), seeded.admin)
    assert resp.status_code == 200, resp.text
    assert user_row(app_engine, seeded.id, seeded.admin.id)["active"] is False


def test_the_remaining_admin_cannot_then_remove_themselves(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    second = create_user(app_engine, seeded.id, role="admin")
    survivor = api.login_as(second)
    assert deactivate(survivor, seeded.admin).status_code == 200
    assert_refused_as_invariant(deactivate(survivor, second))
    assert_refused_as_invariant(demote(survivor, second))
    assert active_admins(app_engine, seeded.id) == 1


# --- two admins at the same moment ------------------------------------------------------------------
@pytest.mark.parametrize("action", [demote, deactivate], ids=["demote", "deactivate"])
def test_two_admins_removing_each_other_concurrently_leave_at_least_one_active_admin(
    api: ApiFactory, app_engine: Engine, action: Any
) -> None:
    for _ in range(ROUNDS):
        tenant = seed_tenant(app_engine)
        assert tenant.admin
        second = create_user(app_engine, tenant.id, role="admin")
        clients = {tenant.admin.id: api.login_as(tenant.admin), second.id: api.login_as(second)}
        victims = {tenant.admin.id: second, second.id: tenant.admin}
        barrier = threading.Barrier(2, timeout=30)
        outcome: dict[UUID, httpx.Response | BaseException] = {}

        def go(
            actor_id: UUID,
            tenant_clients: dict[UUID, ApiClient] = clients,
            tenant_victims: dict[UUID, SeededUser] = victims,
            gate: threading.Barrier = barrier,
            results: dict[UUID, httpx.Response | BaseException] = outcome,
        ) -> None:
            try:
                gate.wait()
                results[actor_id] = action(tenant_clients[actor_id], tenant_victims[actor_id])
            except BaseException as exc:
                results[actor_id] = exc

        threads = [threading.Thread(target=go, args=(actor_id,)) for actor_id in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)

        errors = [r for r in outcome.values() if isinstance(r, BaseException)]
        assert not errors, errors
        statuses = sorted(r.status_code for r in outcome.values() if isinstance(r, httpx.Response))
        assert len(statuses) == 2
        assert active_admins(app_engine, tenant.id) >= 1, f"tenant locked out, statuses {statuses}"
        losers = [s for s in statuses if s != 200]
        # 409 (deadlock/serialisation) or 422 (guard) is the contract; 401/403 only when the other command had
        # already committed before this request authenticated (it was no longer an admin / had no session).
        assert all(s in (401, 403, 409, 422) for s in losers), f"unexpected loser status {statuses}"
        assert statuses.count(200) <= 1, f"both removals succeeded: {statuses}"
