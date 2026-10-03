"""Demo seed (`python -m seeds.demo`): one demo tenant, two plants and four users with KNOWN dev passwords.

Local development only: the script refuses to run in any other `QL_ENV`, because the passwords below are public.
Idempotent: if the demo admin already exists nothing is created. Grows each phase towards blueprint 24.1.6 (P09).
"""

import sys
from uuid import UUID

from sqlalchemy import text

from app.core.audit.writer import record_activity
from app.core.auth.passwords import hash_password
from app.core.config import get_settings
from app.core.db import get_engine, tenant_tx
from app.core.ids import new_id
from app.core.models import Plant, Tenant, User
from app.core.permissions import Actor

DEMO_TENANT_NAME = "Demo Manufacturing Pvt Ltd"

# key -> (email, dev password). Public by design: never seeded outside QL_ENV=local.
DEMO_USERS: dict[str, tuple[str, str]] = {
    "admin": ("admin@demo.qualloop.test", "Demo-Admin-Pass-2026"),
    "quality_approver": ("approver@demo.qualloop.test", "Demo-Approver-Pass-2026"),
    "quality": ("quality@demo.qualloop.test", "Demo-Quality-Pass-2026"),
    "viewer": ("viewer@demo.qualloop.test", "Demo-Viewer-Pass-2026"),
}

# code, name, address
DEMO_PLANTS = (
    ("CHAKAN", "Chakan Plant", "MIDC Chakan, Pune"),
    ("PUNE2", "Pune Plant 2", "Hinjewadi, Pune"),
)


def _exists(email: str) -> bool:
    with get_engine().connect() as conn:
        return (
            conn.execute(text("SELECT 1 FROM app_resolve_login(:email)"), {"email": email}).first()
            is not None
        )


def seed() -> UUID | None:
    """Create the demo tenant. Returns its id, or None when it already exists."""
    if _exists(DEMO_USERS["admin"][0]):
        return None
    tenant_id = new_id()
    with tenant_tx(tenant_id, actor_type="system") as session:
        session.add(Tenant(id=tenant_id, tenant_id=tenant_id, name=DEMO_TENANT_NAME, plan="pilot"))
        session.flush()  # tenants first: every other row references it
        plants = [
            Plant(id=new_id(), tenant_id=tenant_id, name=n, code=c, address=a)
            for c, n, a in DEMO_PLANTS
        ]
        session.add_all(plants)
        session.flush()
        plant_ids = [p.id for p in plants]
        users: tuple[tuple[str, str, bool, list[UUID]], ...] = (
            ("admin", "admin", False, []),
            ("quality_approver", "quality", True, plant_ids),
            ("quality", "quality", False, plant_ids[:1]),
            ("viewer", "viewer", False, plant_ids),
        )
        for key, role, can_approve, scope in users:
            email, password = DEMO_USERS[key]
            session.add(
                User(
                    id=new_id(),
                    tenant_id=tenant_id,
                    email=email,
                    name=key.replace("_", " ").title(),
                    role=role,
                    can_approve=can_approve,
                    plant_ids=list(scope),
                    active=True,
                    password_hash=hash_password(password),
                )
            )
        session.flush()
        record_activity(
            session,
            actor=Actor("system", None, tenant_id, "admin", False, ()),
            object_type="tenant",
            object_id=tenant_id,
            action="seed.demo",
            after={"name": DEMO_TENANT_NAME},
            reason="Demo seed (local development)",
        )
    return tenant_id


def main() -> None:
    settings = get_settings()
    if settings.env != "local":
        print(
            f"refusing to seed demo data: QL_ENV is {settings.env!r}, demo users have public passwords "
            "and are only allowed when QL_ENV is 'local'",
            file=sys.stderr,
        )
        raise SystemExit(1)
    tenant_id = seed()
    if tenant_id is None:
        print("demo data already present; nothing to do")
        return
    print(
        f"seeded demo tenant {tenant_id} with {len(DEMO_PLANTS)} plants and {len(DEMO_USERS)} users"
    )
    for key, (email, password) in DEMO_USERS.items():
        print(f"  {key:17} {email}  {password}")


if __name__ == "__main__":
    main()
