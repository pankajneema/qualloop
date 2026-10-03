"""API.md 3.2 / 5: customers, parts, customer_parts (many-to-many) and supplier_parts (with ppm_target).

INV-MST-01, INV-PLT-08 (archive, picker exclusion), A-75, A-54 (ppm_target > 0)."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from tests.factories.api import ApiClient, ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.masters import (
    OK,
    list_all,
    make_customer,
    make_part,
    make_supplier,
    make_supplier_part,
    part_body,
)

pytestmark = pytest.mark.integration


# =================================================================================================
# customers
# =================================================================================================
def test_create_customer_update_and_archive(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    customer = make_customer(quality, name="Tata Motors", code="TML")
    assert {"id", "name", "code", "archived_at"} <= set(customer) and customer[
        "archived_at"
    ] is None
    renamed = quality.post(f"/customers/{customer['id']}/update", {"name": "Tata Motors Ltd"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Tata Motors Ltd"
    assert quality.post(f"/customers/{customer['id']}/archive", {}).status_code == 422, (
        "archive needs a reason"
    )
    archived = quality.post(f"/customers/{customer['id']}/archive", {"reason": "Contract ended"})
    assert archived.status_code == 200 and archived.json()["archived_at"] is not None
    assert list_all(quality, "/customers") == []
    assert [c["id"] for c in list_all(quality, "/customers", archived="true")] == [customer["id"]]
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM customers")) == 1, (
        "archived, never deleted"
    )


@pytest.mark.parametrize(
    "body", [{"name": "", "code": "X"}, {"name": "X", "code": ""}, {"name": "X"}, {"code": "X"}]
)
def test_create_customer_rejects_invalid_input(quality: ApiClient, body: dict[str, Any]) -> None:
    resp = quality.post("/customers", body)
    assert resp.status_code == 422 and problem(resp)["code"] == "validation_error"


def test_customer_code_is_unique_per_tenant_but_reusable_across_tenants(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    qa, qb = api.login_as(a.quality), api.login_as(b.quality)
    make_customer(qa, code="OEM-1")
    assert qa.post("/customers", {"name": "Other", "code": "OEM-1"}).status_code in (409, 422)
    make_customer(qb, code="OEM-1")


# =================================================================================================
# parts
# =================================================================================================
def test_create_part_has_no_customer_id_anywhere(quality: ApiClient, owner_engine: Engine) -> None:
    """INV-MST-01 (schema): a part belongs to no single customer."""
    part = make_part(quality)
    assert "customer_id" not in part
    with owner_engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'parts'"
                )
            )
        }
    assert "customer_id" not in cols
    resp = quality.post("/parts", part_body(customer_id=str(UUID(int=1))))
    assert resp.status_code == 422


def test_part_can_link_to_many_customers(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-MST-01: customer_parts is many-to-many in both directions."""
    part, other_part = make_part(quality), make_part(quality)
    customers = [make_customer(quality) for _ in range(3)]
    for customer in customers:
        resp = quality.post(
            "/customer-parts",
            {
                "customer_id": customer["id"],
                "part_id": part["id"],
                "customer_part_no": f"CP-{customer['code']}",
            },
        )
        assert resp.status_code in OK, resp.text
    assert (
        quality.post(
            "/customer-parts", {"customer_id": customers[0]["id"], "part_id": other_part["id"]}
        ).status_code
        in OK
    ), "one customer can also have many parts"
    links = list_all(quality, "/customer-parts", part_id=part["id"])
    assert {link["customer_id"] for link in links} == {c["id"] for c in customers}
    assert {link["customer_part_no"] for link in links} == {f"CP-{c['code']}" for c in customers}
    rows = fetch_all(
        app_engine,
        seeded.id,
        "SELECT 1 FROM customer_parts WHERE part_id = :p",
        {"p": UUID(part["id"])},
    )
    assert len(rows) == 3
    assert len(list_all(quality, "/customer-parts", customer_id=customers[0]["id"])) == 2


def test_the_same_customer_part_pair_cannot_be_linked_twice(quality: ApiClient) -> None:
    part, customer = make_part(quality), make_customer(quality)
    body = {"customer_id": customer["id"], "part_id": part["id"]}
    assert quality.post("/customer-parts", body).status_code in OK
    again = quality.post("/customer-parts", body)
    assert again.status_code == 409, again.text  # A-119: an active pair is a conflict
    problem(again)


def test_unlinking_a_customer_part_archives_it(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    part, customer = make_part(quality), make_customer(quality)
    link = quality.post(
        "/customer-parts", {"customer_id": customer["id"], "part_id": part["id"]}
    ).json()
    resp = quality.post(f"/customer-parts/{link['id']}/archive", {})
    assert resp.status_code == 200 and resp.json()["archived_at"] is not None
    assert list_all(quality, "/customer-parts", part_id=part["id"]) == []
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM customer_parts")) == 1
    assert quality.post(f"/customer-parts/{link['id']}/archive", {}).status_code == 409


def test_customer_part_needs_existing_live_customer_and_part(quality: ApiClient) -> None:
    part, customer = make_part(quality), make_customer(quality)
    ghost = "0198f0f0-0000-7000-8000-000000000000"
    for body in (
        {"customer_id": ghost, "part_id": part["id"]},
        {"customer_id": customer["id"], "part_id": ghost},
    ):
        assert quality.post("/customer-parts", body).status_code in (404, 422)
    quality.post(f"/parts/{part['id']}/archive", {"reason": "Obsolete"})
    assert quality.post(
        "/customer-parts", {"customer_id": customer["id"], "part_id": part["id"]}
    ).status_code in (409, 422)


def test_create_part_returns_the_read_model(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    body = part_body(
        part_no="BRK-1001", name="Brake bracket", category="Fabricated", current_revision="C"
    )
    resp = quality.post("/parts", body)
    assert resp.status_code in OK, resp.text
    data = resp.json()
    assert {k: data[k] for k in body} == body and data["archived_at"] is None
    optional = quality.post("/parts", {"part_no": "BRK-1002", "name": "Plain"})
    assert optional.status_code in OK and optional.json()["current_revision"] is None


@pytest.mark.parametrize(
    "body", [{"part_no": ""}, {"name": ""}, {"part_no": "  "}, {"part_no": 12}, {"name": None}]
)
def test_create_part_rejects_invalid_input(quality: ApiClient, body: dict[str, Any]) -> None:
    resp = quality.post("/parts", part_body(**body))
    assert resp.status_code == 422 and problem(resp)["code"] == "validation_error"


def test_part_no_is_unique_per_tenant(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    qa = api.login_as(a.quality)
    make_part(qa, part_no="PN-1")
    assert qa.post("/parts", part_body(part_no="PN-1")).status_code in (409, 422)
    make_part(api.login_as(b.quality), part_no="PN-1")


def test_update_part_changes_the_sent_fields(quality: ApiClient) -> None:
    part = make_part(quality, current_revision="A")
    resp = quality.post(f"/parts/{part['id']}/update", {"name": "Renamed", "current_revision": "B"})
    assert resp.status_code == 200
    assert (resp.json()["name"], resp.json()["current_revision"], resp.json()["part_no"]) == (
        "Renamed",
        "B",
        part["part_no"],
    )
    assert (
        quality.post(
            f"/parts/{part['id']}/update", {"archived_at": "2026-01-01T00:00:00Z"}
        ).status_code
        == 422
    )


def test_archived_part_hidden_from_capture_search(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-PLT-08: archived masters leave the pickers (the part list and a supplier's part list used by capture)
    but stay readable and stay in history."""
    supplier = make_supplier(quality)
    live, retired = make_part(quality), make_part(quality)
    link_live = make_supplier_part(quality, supplier["id"], live["id"])
    link_retired = make_supplier_part(quality, supplier["id"], retired["id"])
    assert quality.post(f"/parts/{retired['id']}/archive", {}).status_code == 422, (
        "archive needs a reason"
    )
    resp = quality.post(f"/parts/{retired['id']}/archive", {"reason": "Part discontinued"})
    assert resp.status_code == 200 and resp.json()["archived_at"] is not None
    assert [p["id"] for p in list_all(quality, "/parts")] == [live["id"]]
    assert retired["id"] in {p["id"] for p in list_all(quality, "/parts", archived="true")}
    picker = list_all(quality, "/supplier-parts", supplier_id=supplier["id"])
    assert [link["id"] for link in picker] == [link_live["id"]]
    assert quality.get(f"/parts/{retired['id']}").status_code == 200, (
        "history still resolves the part"
    )
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM parts")) == 2
    still = fetch_all(
        app_engine,
        seeded.id,
        "SELECT archived_at FROM supplier_parts WHERE id = :i",
        {"i": UUID(link_retired["id"])},
    )
    assert len(still) == 1, "the link row itself is kept"
    again = quality.post(f"/parts/{retired['id']}/archive", {"reason": "twice"})
    assert again.status_code == 409 and problem(again)["code"] == "invalid_transition"


def test_part_list_is_sorted_by_part_no_with_keyset_paging(quality: ApiClient) -> None:
    numbers = ["PN-010", "PN-002", "PN-100", "PN-001", "PN-050"]
    for number in numbers:
        make_part(quality, part_no=number)
    assert [p["part_no"] for p in list_all(quality, "/parts")] == sorted(numbers)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        page = quality.get(
            "/parts", params={"limit": 2, **({"cursor": cursor} if cursor else {})}
        ).json()
        seen += [p["part_no"] for p in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(numbers)
    resp = quality.get("/parts", params={"sort": "name"})
    assert resp.status_code == 400 and problem(resp)["code"] == "bad_request"


def test_get_part_unknown_is_404(quality: ApiClient) -> None:
    part = make_part(quality)
    assert quality.get(f"/parts/{part['id']}").status_code == 200, "control: the route exists"
    assert quality.get("/parts/0198f0f0-0000-7000-8000-000000000000").status_code == 404


# =================================================================================================
# supplier_parts
# =================================================================================================
def test_create_supplier_part_defaults_to_active_and_keeps_ppm_target(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    link = make_supplier_part(
        quality, supplier["id"], part["id"], supplier_part_no="V-77", ppm_target=250
    )
    assert (link["status"], link["ppm_target"], link["supplier_part_no"]) == ("active", 250, "V-77")
    assert (link["supplier_id"], link["part_id"], link["archived_at"]) == (
        supplier["id"],
        part["id"],
        None,
    )
    plain = make_supplier_part(quality, make_supplier(quality)["id"], part["id"])
    assert plain["ppm_target"] is None, (
        "no override: the tenant default applies later (blueprint 14.4)"
    )


@pytest.mark.parametrize("bad", [0, -1, 1.5, "10", True, 2**31])
def test_supplier_part_ppm_target_must_be_a_positive_integer(quality: ApiClient, bad: Any) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    resp = quality.post(
        "/supplier-parts", {"supplier_id": supplier["id"], "part_id": part["id"], "ppm_target": bad}
    )
    assert resp.status_code == 422, f"{bad!r}: {resp.text}"
    assert problem(resp)["code"] == "validation_error"


def test_a_supplier_part_pair_is_unique_and_references_must_exist(quality: ApiClient) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    make_supplier_part(quality, supplier["id"], part["id"])
    assert quality.post(
        "/supplier-parts", {"supplier_id": supplier["id"], "part_id": part["id"]}
    ).status_code in (409, 422)
    ghost = "0198f0f0-0000-7000-8000-000000000000"
    assert quality.post(
        "/supplier-parts", {"supplier_id": ghost, "part_id": part["id"]}
    ).status_code in (404, 422)
    assert quality.post(
        "/supplier-parts", {"supplier_id": supplier["id"], "part_id": ghost}
    ).status_code in (404, 422)


def test_update_supplier_part_changes_ppm_target_and_part_number(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    link = make_supplier_part(quality, supplier["id"], part["id"], ppm_target=250)
    resp = quality.post(
        f"/supplier-parts/{link['id']}/update", {"ppm_target": 120, "supplier_part_no": "V-9"}
    )
    assert resp.status_code == 200 and (
        resp.json()["ppm_target"],
        resp.json()["supplier_part_no"],
    ) == (120, "V-9")
    for bad in (0, -3, 2.5):
        assert (
            quality.post(f"/supplier-parts/{link['id']}/update", {"ppm_target": bad}).status_code
            == 422
        )
    assert (
        fetch_all(app_engine, seeded.id, "SELECT ppm_target FROM supplier_parts")[0]["ppm_target"]
        == 120
    )


def test_supplier_part_update_cannot_change_status_supplier_or_part(quality: ApiClient) -> None:
    """INV-PLT-06: `/update` bodies carry no `status`; the pair identity is immutable."""
    supplier, part = make_supplier(quality), make_part(quality)
    link = make_supplier_part(quality, supplier["id"], part["id"])
    for body in (
        {"status": "inactive"},
        {"supplier_id": make_supplier(quality)["id"]},
        {"part_id": make_part(quality)["id"]},
    ):
        assert quality.post(f"/supplier-parts/{link['id']}/update", body).status_code == 422, body


def test_archiving_a_supplier_part_removes_it_from_lists_and_keeps_the_row(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    link = make_supplier_part(quality, supplier["id"], part["id"])
    resp = quality.post(f"/supplier-parts/{link['id']}/archive", {})
    assert resp.status_code == 200 and resp.json()["archived_at"] is not None
    assert list_all(quality, "/supplier-parts", supplier_id=supplier["id"]) == []
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_parts")) == 1
    assert quality.post(f"/supplier-parts/{link['id']}/archive", {}).status_code == 409


def test_supplier_parts_can_be_filtered_by_supplier_and_by_part(quality: ApiClient) -> None:
    s1, s2 = make_supplier(quality), make_supplier(quality)
    p1, p2 = make_part(quality), make_part(quality)
    a, b, c = (
        make_supplier_part(quality, s, p["id"])
        for s, p in ((s1["id"], p1), (s1["id"], p2), (s2["id"], p1))
    )
    assert {x["id"] for x in list_all(quality, "/supplier-parts", supplier_id=s1["id"])} == {
        a["id"],
        b["id"],
    }
    assert {x["id"] for x in list_all(quality, "/supplier-parts", part_id=p1["id"])} == {
        a["id"],
        c["id"],
    }
    assert {x["id"] for x in list_all(quality, "/supplier-parts")} == {a["id"], b["id"], c["id"]}


def test_catalog_commands_replay_with_an_idempotency_key(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    body, key = part_body(), new_key()
    first = quality.post("/parts", body, key=key)
    again = quality.post("/parts", body, key=key)
    assert again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM parts")) == 1


def test_every_role_can_read_the_catalog_lists(
    api: ApiFactory, seeded: SeededTenant, quality: ApiClient
) -> None:
    supplier, part, customer = make_supplier(quality), make_part(quality), make_customer(quality)
    make_supplier_part(quality, supplier["id"], part["id"])
    quality.post("/customer-parts", {"customer_id": customer["id"], "part_id": part["id"]})
    for user in (seeded.admin, seeded.quality, seeded.viewer):
        assert user
        client = api.login_as(user)
        for path in ("/customers", "/parts", "/supplier-parts", "/customer-parts"):
            resp = client.get(path)
            assert resp.status_code == 200 and len(resp.json()["items"]) == 1, (user.role, path)
        assert client.get(f"/parts/{part['id']}").status_code == 200


# =================================================================================================
# A-119: re-linking an archived pair restores the row
# =================================================================================================
def restore_actions(engine: Engine, tenant: UUID, object_id: str) -> list[str]:
    rows = fetch_all(
        engine,
        tenant,
        "SELECT action FROM activity_log WHERE object_id = :i",
        {"i": UUID(object_id)},
    )
    return [r["action"] for r in rows if r["action"].endswith("restore")]


def test_linking_an_archived_customer_part_pair_restores_the_same_row(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    part, customer = make_part(quality), make_customer(quality)
    body = {"customer_id": customer["id"], "part_id": part["id"]}
    link = quality.post("/customer-parts", body).json()
    assert quality.post(f"/customer-parts/{link['id']}/archive", {}).status_code == 200
    assert list_all(quality, "/customer-parts", part_id=part["id"]) == []

    resp = quality.post("/customer-parts", {**body, "customer_part_no": "CP-NEW"})
    assert resp.status_code in OK, resp.text
    assert resp.json()["id"] == link["id"], "the archived row comes back; no second row"
    assert resp.json()["archived_at"] is None
    assert [x["id"] for x in list_all(quality, "/customer-parts", part_id=part["id"])] == [
        link["id"]
    ]
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM customer_parts")) == 1
    assert len(restore_actions(app_engine, seeded.id, link["id"])) == 1
    assert quality.post("/customer-parts", body).status_code == 409, "now active again"


def test_linking_an_archived_supplier_part_pair_restores_the_same_row(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    link = make_supplier_part(quality, supplier["id"], part["id"], ppm_target=300)
    assert quality.post(f"/supplier-parts/{link['id']}/archive", {}).status_code == 200
    assert list_all(quality, "/supplier-parts", supplier_id=supplier["id"]) == []

    resp = quality.post("/supplier-parts", {"supplier_id": supplier["id"], "part_id": part["id"]})
    assert resp.status_code in OK, resp.text
    data = resp.json()
    assert data["id"] == link["id"] and data["archived_at"] is None
    assert data["status"] == "active", "A-117: links are created active"
    assert [x["id"] for x in list_all(quality, "/supplier-parts", supplier_id=supplier["id"])] == [
        link["id"]
    ]
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_parts")) == 1
    assert len(restore_actions(app_engine, seeded.id, link["id"])) == 1
    again = quality.post("/supplier-parts", {"supplier_id": supplier["id"], "part_id": part["id"]})
    assert again.status_code == 409


def test_a_new_supplier_part_link_is_active_and_create_takes_no_status(quality: ApiClient) -> None:
    """A-117: links are created `active`; there is no way to create or update one as `inactive`."""
    supplier, part = make_supplier(quality), make_part(quality)
    assert make_supplier_part(quality, supplier["id"], part["id"])["status"] == "active"
    resp = quality.post(
        "/supplier-parts",
        {"supplier_id": make_supplier(quality)["id"], "part_id": part["id"], "status": "inactive"},
    )
    assert resp.status_code == 422, resp.text
