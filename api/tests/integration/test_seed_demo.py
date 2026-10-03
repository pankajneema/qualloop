"""PHASES P01 / REPO_LAYOUT: `python -m seeds.demo` creates one demo tenant, two plants and four users with known
dev passwords; it is idempotent and refuses to run outside local development."""

import os
import subprocess
import sys
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from tests.conftest import API_ROOT
from tests.factories.api import ApiFactory
from tests.factories.contract import load
from tests.factories.db import fetch_all

pytestmark = pytest.mark.integration

ROLES = {
    "admin": ("admin", False),
    "quality_approver": ("quality", True),
    "quality": ("quality", False),
    "viewer": ("viewer", False),
}


def run_seed(env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **(env_overrides or {})}
    return subprocess.run(
        [sys.executable, "-m", "seeds.demo"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def tenant_of(engine: Engine, email: str) -> UUID | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM app_resolve_login(:e)"), {"e": email}).first()
    if row is None:
        return None
    ids = [v for v in row if isinstance(v, UUID)]
    return ids[0]


def demo_users() -> dict[str, tuple[str, str]]:
    users: dict[str, tuple[str, str]] = load("seeds.demo", "DEMO_USERS")
    return users


def test_seed_creates_one_tenant_two_plants_and_the_four_documented_users(
    app_engine: Engine,
) -> None:
    done = run_seed()
    assert done.returncode == 0, done.stderr
    users = demo_users()
    assert set(users) == set(ROLES)
    tenants = {tenant_of(app_engine, email) for email, _ in users.values()}
    assert len(tenants) == 1 and None not in tenants
    tenant = tenants.pop()
    assert tenant is not None
    assert len(fetch_all(app_engine, tenant, "SELECT 1 FROM plants")) == 2
    rows = fetch_all(
        app_engine, tenant, "SELECT email, role, can_approve, active, password_hash FROM users"
    )
    by_email = {r["email"].lower(): r for r in rows}
    assert len(rows) == 4
    for key, (email, _password) in users.items():
        role, can_approve = ROLES[key]
        row = by_email[email.lower()]
        assert (row["role"], row["can_approve"], row["active"]) == (role, can_approve, True)
        assert row["password_hash"].startswith("$argon2id$")


def test_seed_is_idempotent(app_engine: Engine) -> None:
    assert run_seed().returncode == 0
    emails = [email for email, _ in demo_users().values()]
    tenant = tenant_of(app_engine, emails[0])
    assert tenant is not None
    before = (
        len(fetch_all(app_engine, tenant, "SELECT 1 FROM plants")),
        len(fetch_all(app_engine, tenant, "SELECT 1 FROM users")),
    )
    again = run_seed()
    assert again.returncode == 0, again.stderr
    after = (
        len(fetch_all(app_engine, tenant, "SELECT 1 FROM plants")),
        len(fetch_all(app_engine, tenant, "SELECT 1 FROM users")),
    )
    assert before == after == (2, 4)
    assert tenant_of(app_engine, emails[0]) == tenant


def test_every_seeded_user_can_log_in_with_the_documented_dev_password(api: ApiFactory) -> None:
    assert run_seed().returncode == 0
    for i, (email, password) in enumerate(demo_users().values()):
        resp = api.anonymous(f"203.0.113.{60 + i}").login(email, password)
        assert resp.status_code == 200, f"{email}: {resp.text}"


def test_seed_refuses_to_run_outside_local_development(app_engine: Engine) -> None:
    """Known passwords must never reach staging or production."""
    done: Any = run_seed(
        {
            "QL_ENV": "production",
            "QL_SESSION_SECRET": "s" * 40,
            "QL_HMAC_SECRET": "h" * 40,
        }
    )
    assert done.returncode != 0
    assert "local" in (done.stderr + done.stdout).lower()
