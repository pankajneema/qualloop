"""INV-SEC-01 / blueprint 21.2 for the P02 resources: tenant A cannot read or write tenant B suppliers, contacts, parts,
customers or import batches over the API. Foreign objects are 404 (never 403) and left untouched."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.imports import Importer, file_for, mapping_for, supplier_row
from tests.factories.masters import (
    contact_body,
    list_all,
    make_contact,
    make_customer,
    make_part,
    make_supplier,
    make_supplier_part,
)
from tests.integration.auth.helpers import strip_volatile
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration


class World:
    """Two tenants; B owns one of everything, A's approver and quality clients attack it."""

    def __init__(self, api: ApiFactory, a: SeededTenant, b: SeededTenant) -> None:
        assert a.quality and a.approver and b.quality and b.approver
        self.a, self.b = a, b
        self.qa, self.aa = api.login_as(a.quality), api.login_as(a.approver)
        self.qb = qb = api.login_as(b.quality)
        self.supplier = make_supplier(api.login_as(b.approver), status="approved")
        self.contact = make_contact(qb, self.supplier["id"])
        self.part = make_part(qb)
        self.customer = make_customer(qb)
        self.supplier_part = make_supplier_part(
            qb, self.supplier["id"], self.part["id"], ppm_target=300
        )
        self.customer_part = qb.post(
            "/customer-parts", {"customer_id": self.customer["id"], "part_id": self.part["id"]}
        ).json()


@pytest.fixture
def world(api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]) -> World:
    return World(api, *seeded_pair)


def row(engine: Engine, tenant: UUID, table: str, object_id: str) -> dict[str, Any]:
    return fetch_all(
        engine, tenant, f"SELECT * FROM {table} WHERE id = :i", {"i": UUID(object_id)}
    )[0]


def test_tenant_a_cannot_read_tenant_b_suppliers_api(world: World) -> None:
    ids = {s["id"] for s in list_all(world.qa, "/suppliers", archived="true")} | {
        s["id"] for s in list_all(world.qa, "/suppliers")
    }
    assert world.supplier["id"] not in ids
    for client in (world.qa, world.aa):
        resp = client.get(f"/suppliers/{world.supplier['id']}")
        assert resp.status_code == 404 and problem(resp)["code"] == "not_found"
        assert client.get(f"/suppliers/{world.supplier['id']}/contacts").status_code == 404
    assert list_all(world.qa, "/suppliers", q=world.supplier["name"]) == []
    assert list_all(world.qa, "/suppliers", q=world.supplier["code"]) == []


def test_tenant_a_cannot_write_tenant_b_supplier_api(world: World, app_engine: Engine) -> None:
    before = row(app_engine, world.b.id, "suppliers", world.supplier["id"])
    sid = world.supplier["id"]
    attempts = [
        (world.qa, f"/suppliers/{sid}/update", {"name": "Hijacked"}),
        (world.qa, f"/suppliers/{sid}/archive", {"reason": "attack"}),
        (world.aa, f"/suppliers/{sid}/change-status", {"status": "blocked", "reason": "attack"}),
        (world.qa, f"/suppliers/{sid}/contacts", contact_body()),
    ]
    for client, path, body in attempts:
        resp = client.post(path, body)
        assert resp.status_code == 404, f"{path}: {resp.status_code}"
        assert problem(resp)["code"] == "not_found"
    assert row(app_engine, world.b.id, "suppliers", sid) == before
    assert len(fetch_all(app_engine, world.b.id, "SELECT 1 FROM supplier_contacts")) == 1
    assert len(fetch_all(app_engine, world.a.id, "SELECT 1 FROM supplier_contacts")) == 0


def test_a_foreign_object_and_a_missing_object_look_identical(world: World) -> None:
    ghost = "0198f0f0-0000-7000-8000-000000000000"
    for template in ("/suppliers/{}", "/contacts/{}", "/parts/{}"):
        foreign_id = {
            "/suppliers/{}": world.supplier,
            "/contacts/{}": world.contact,
            "/parts/{}": world.part,
        }[template]["id"]
        foreign = world.qa.get(template.format(foreign_id))
        missing = world.qa.get(template.format(ghost))
        assert foreign.status_code == missing.status_code == 404
        assert strip_volatile(problem(foreign)) == strip_volatile(problem(missing))


def test_tenant_a_cannot_touch_tenant_b_contacts_api(
    world: World, app_engine: Engine, clean_outbox: None
) -> None:
    cid = world.contact["id"]
    before = row(app_engine, world.b.id, "supplier_contacts", cid)
    assert world.qa.get(f"/contacts/{cid}").status_code == 404
    for path, body in (
        (f"/contacts/{cid}/update", {"name": "Hijacked"}),
        (f"/contacts/{cid}/set-quality-contact", {}),
        (f"/contacts/{cid}/disable", {"reason": "attack"}),
        (f"/contacts/{cid}/replace", {**contact_body(), "reason": "attack"}),
        (f"/contacts/{cid}/verify/start", {"channel": "mobile"}),
        (f"/contacts/{cid}/verify/confirm", {"channel": "mobile", "code": "123456"}),
        (
            f"/contacts/{cid}/consents",
            {"channel": "email", "status": "opted_in", "source": "manual"},
        ),
    ):
        assert world.qa.post(path, body).status_code == 404, path
    assert row(app_engine, world.b.id, "supplier_contacts", cid) == before
    assert fetch_all(app_engine, world.b.id, "SELECT 1 FROM contact_consents") == []
    assert all(r["object_id"] != UUID(cid) for r in log_rows(app_engine, world.a.id))
    assert all(e["aggregate_id"] != UUID(cid) for e in outbox_rows(app_engine, world.a.id))
    assert [
        r for r in log_rows(app_engine, world.b.id, UUID(cid)) if "disable" in r["action"]
    ] == []


def test_tenant_a_cannot_touch_tenant_b_parts_customers_and_links_api(
    world: World, app_engine: Engine
) -> None:
    attacks = [
        ("parts", world.part["id"], f"/parts/{world.part['id']}/update", {"name": "Hijacked"}),
        ("parts", world.part["id"], f"/parts/{world.part['id']}/archive", {"reason": "attack"}),
        (
            "customers",
            world.customer["id"],
            f"/customers/{world.customer['id']}/update",
            {"name": "Hijacked"},
        ),
        (
            "customers",
            world.customer["id"],
            f"/customers/{world.customer['id']}/archive",
            {"reason": "attack"},
        ),
        (
            "supplier_parts",
            world.supplier_part["id"],
            f"/supplier-parts/{world.supplier_part['id']}/update",
            {"ppm_target": 1},
        ),
        (
            "supplier_parts",
            world.supplier_part["id"],
            f"/supplier-parts/{world.supplier_part['id']}/archive",
            {},
        ),
        (
            "customer_parts",
            world.customer_part["id"],
            f"/customer-parts/{world.customer_part['id']}/archive",
            {},
        ),
    ]
    for table, oid, path, body in attacks:
        before = row(app_engine, world.b.id, table, oid)
        assert world.qa.post(path, body).status_code == 404, path
        assert row(app_engine, world.b.id, table, oid) == before, path


def test_tenant_a_lists_never_include_tenant_b_catalogue_rows(world: World) -> None:
    for path in ("/parts", "/customers", "/supplier-parts", "/customer-parts"):
        assert list_all(world.qa, path) == [], path
    for path in ("/parts", "/customers"):
        assert list_all(world.qa, path, archived="true") == [], path


def test_links_cannot_join_an_own_object_to_a_foreign_one(world: World, app_engine: Engine) -> None:
    mine_supplier, mine_part, mine_customer = (
        make_supplier(world.qa),
        make_part(world.qa),
        make_customer(world.qa),
    )
    attempts = [
        ("/supplier-parts", {"supplier_id": mine_supplier["id"], "part_id": world.part["id"]}),
        ("/supplier-parts", {"supplier_id": world.supplier["id"], "part_id": mine_part["id"]}),
        ("/customer-parts", {"customer_id": mine_customer["id"], "part_id": world.part["id"]}),
        ("/customer-parts", {"customer_id": world.customer["id"], "part_id": mine_part["id"]}),
    ]
    for path, body in attempts:
        resp = world.qa.post(path, body)
        assert resp.status_code in (404, 422), f"{path}: {resp.status_code}"
    assert fetch_all(app_engine, world.a.id, "SELECT 1 FROM supplier_parts") == []
    assert fetch_all(app_engine, world.a.id, "SELECT 1 FROM customer_parts") == []


def test_same_codes_in_two_tenants_do_not_collide_or_leak(world: World) -> None:
    """Uniqueness is per tenant: A can reuse B's supplier code and part number without learning that B has them."""
    assert world.qa.post(
        "/suppliers",
        {**{k: world.supplier[k] for k in ("code", "name", "category")}, "status": "approved"},
    ).status_code in (200, 201)
    assert world.qa.post(
        "/parts", {"part_no": world.part["part_no"], "name": "Mine"}
    ).status_code in (200, 201)
    assert world.qa.post(
        "/customers", {"name": "Mine", "code": world.customer["code"]}
    ).status_code in (200, 201)


# --- imports ---------------------------------------------------------------------------------------------
@pytest.fixture
def foreign_batches(world: World, drain: Callable[[], None]) -> dict[str, str]:
    """Tenant B's batches in three stages: uploaded, validated and completed."""
    imp = Importer(world.qb, world.b.id, drain)
    data, name, ctype = file_for("suppliers", [supplier_row(i) for i in range(3)])
    uploaded = imp.upload("suppliers", data, name, ctype)
    other, name2, ctype2 = file_for("suppliers", [supplier_row(10 + i) for i in range(3)])
    validated = imp.run("suppliers", other, name2, ctype2, confirm=False)
    last, name3, ctype3 = file_for("suppliers", [supplier_row(20 + i) for i in range(3)])
    completed = imp.run("suppliers", last, name3, ctype3)
    return {"uploaded": uploaded["id"], "validated": validated["id"], "completed": completed["id"]}


def test_tenant_a_cannot_read_tenant_b_import_batches_api(
    world: World, foreign_batches: dict[str, str]
) -> None:
    assert list_all(world.qa, "/imports") == []
    for bid in foreign_batches.values():
        for path in (
            f"/imports/{bid}",
            f"/imports/{bid}/preview",
            f"/imports/{bid}/records",
            f"/imports/{bid}/report.xlsx",
        ):
            resp = world.qa.get(path)
            assert resp.status_code == 404, f"{path}: {resp.status_code}"
            assert problem(resp)["code"] == "not_found"


def test_tenant_a_cannot_drive_tenant_b_import_batches_api(
    world: World, foreign_batches: dict[str, str], app_engine: Engine
) -> None:
    before = {
        k: row(app_engine, world.b.id, "import_batches", v) for k, v in foreign_batches.items()
    }
    calls = [
        ("uploaded", "/map", {"mapping": mapping_for("suppliers")}),
        ("uploaded", "/validate", {}),
        ("uploaded", "/cancel", {}),
        ("validated", "/confirm", {"accept_partial": True}),
        ("validated", "/cancel", {}),
    ]
    for stage, suffix, body in calls:
        resp = world.qa.post(f"/imports/{foreign_batches[stage]}{suffix}", body, key=new_key())
        assert resp.status_code == 404, f"{stage}{suffix}: {resp.status_code}"
    after = {
        k: row(app_engine, world.b.id, "import_batches", v) for k, v in foreign_batches.items()
    }
    assert after == before
    assert fetch_all(app_engine, world.a.id, "SELECT 1 FROM suppliers") == []


def test_tenant_a_cannot_confirm_tenant_b_batch_even_with_a_valid_idempotency_key(
    world: World, foreign_batches: dict[str, str], app_engine: Engine
) -> None:
    count_before = len(fetch_all(app_engine, world.b.id, "SELECT 1 FROM suppliers"))
    resp = world.aa.post(
        f"/imports/{foreign_batches['validated']}/confirm", {"accept_partial": True}, key=new_key()
    )
    assert resp.status_code == 404
    assert len(fetch_all(app_engine, world.b.id, "SELECT 1 FROM suppliers")) == count_before
