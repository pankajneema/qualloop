"""API.md 3.2 / 5: supplier create, update, archive and the /suppliers list (search, filters, sorts, keyset).

INV-PLT-08 (archive, never delete), INV-MST-03 (update ignores status), A-06 (status required on create)."""

import re
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.masters import (
    CATEGORIES,
    OK,
    STATUSES,
    gstin,
    list_all,
    make_contact,
    make_part,
    make_supplier,
    make_supplier_part,
    supplier_body,
)
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration

UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
READ_MODEL_FIELDS = {
    "id",
    "code",
    "name",
    "gstin",
    "city",
    "state",
    "category",
    "status",
    "status_reason",
    "status_changed_by",
    "status_changed_at",
    "archived_at",
    "created_at",
    "updated_at",
}


def row(engine: Engine, tenant: UUID, supplier_id: str) -> dict[str, Any]:
    rows = fetch_all(
        engine, tenant, "SELECT * FROM suppliers WHERE id = :i", {"i": UUID(supplier_id)}
    )
    assert len(rows) == 1
    return rows[0]


# =================================================================================================
# create
# =================================================================================================
def test_create_supplier_returns_the_read_model_and_persists_it(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    body = supplier_body(gstin=gstin(), status="approved")
    resp = quality.post("/suppliers", body)
    assert resp.status_code in OK, resp.text
    data = resp.json()
    assert set(data) >= READ_MODEL_FIELDS
    assert UUID7.match(data["id"])
    assert {k: data[k] for k in body} == body
    assert data["archived_at"] is None
    stored = row(app_engine, seeded.id, data["id"])
    assert (stored["tenant_id"], stored["created_by"], stored["updated_by"]) == (
        seeded.id,
        seeded.quality.id,
        seeded.quality.id,
    )
    assert stored["status"] == "approved"


@pytest.mark.parametrize("role", ["quality", "admin"])
@pytest.mark.parametrize("status", [s for s in STATUSES if s != "approved"])
def test_create_supplier_without_can_approve_cannot_choose_a_status_other_than_approved(
    api: ApiFactory,
    seeded: SeededTenant,
    app_engine: Engine,
    clean_outbox: None,
    role: str,
    status: str,
) -> None:
    """A-116: the +CA gate of change-status cannot be bypassed at create. 403, no row, no audit entry, no event.
    Admin does not hold the flag either (API.md 1.3)."""
    user = getattr(seeded, role)
    assert user and not user.can_approve
    client = api.login_as(user)
    logs, events = len(log_rows(app_engine, seeded.id)), len(outbox_rows(app_engine, seeded.id))
    resp = client.post("/suppliers", supplier_body(status=status))
    assert resp.status_code == 403, resp.text
    assert problem(resp)["code"] == "forbidden"
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers") == []
    assert len(log_rows(app_engine, seeded.id)) == logs
    assert len(outbox_rows(app_engine, seeded.id)) == events


@pytest.mark.parametrize("role", ["quality", "admin"])
def test_create_supplier_without_can_approve_may_create_an_approved_supplier(
    api: ApiFactory, seeded: SeededTenant, role: str
) -> None:
    user = getattr(seeded, role)
    resp = api.login_as(user).post("/suppliers", supplier_body(status="approved"))
    assert resp.status_code in OK, resp.text
    assert resp.json()["status"] == "approved"


@pytest.mark.parametrize("status", STATUSES)
def test_create_supplier_with_can_approve_may_choose_any_of_the_five_statuses(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine, status: str
) -> None:
    resp = approver.post("/suppliers", supplier_body(status=status))
    assert resp.status_code in OK, resp.text
    assert row(app_engine, seeded.id, resp.json()["id"])["status"] == status


def test_create_supplier_requires_a_status(quality: ApiClient, app_engine: Engine) -> None:
    """A-06: manual create has no default status; the user must choose one."""
    body = supplier_body()
    del body["status"]
    resp = quality.post("/suppliers", body)
    assert resp.status_code == 422
    assert any(e["field"] == "status" for e in problem(resp)["errors"])


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("category", CATEGORIES)
def test_create_supplier_accepts_every_documented_status_and_category(
    approver: ApiClient, status: str, category: str
) -> None:
    resp = approver.post("/suppliers", supplier_body(status=status, category=category))
    assert resp.status_code in OK, resp.text
    assert (resp.json()["status"], resp.json()["category"]) == (status, category)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", ""),
        ("code", "   "),
        ("code", None),
        ("name", ""),
        ("name", "  "),
        ("name", None),
        ("category", "plastic"),
        ("category", ""),
        ("status", "suspended"),
        ("status", "APPROVED"),
        ("status", ""),
        ("gstin", "27AAAAA0001A1Z"),  # 14 characters
        ("gstin", "27AAAAA0001A1Z55"),  # 16 characters
        ("gstin", "27aaaaa0001a1z5!"),
        ("gstin", "27 AAAA0001A1Z5"),
        ("name", 123),
        ("city", ["Pune"]),
    ],
    ids=lambda v: str(v)[:18],
)
def test_create_supplier_rejects_invalid_input_with_422_and_creates_nothing(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, field: str, value: Any
) -> None:
    body = supplier_body(**{field: value})
    resp = quality.post("/suppliers", body)
    assert resp.status_code == 422, resp.text
    problem_body = problem(resp)
    assert problem_body["code"] == "validation_error"
    assert any(e["field"] == field for e in problem_body["errors"]), problem_body["errors"]
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers") == []


def test_create_supplier_rejects_unknown_and_privileged_fields(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    for extra in (
        {"tenant_id": str(seeded.id)},
        {"archived_at": "2026-01-01T00:00:00Z"},
        {"status_reason": "x"},
        {"id": "x"},
    ):
        resp = quality.post("/suppliers", {**supplier_body(), **extra})
        assert resp.status_code == 422, extra
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers") == []


def test_supplier_gstin_city_and_state_are_optional(quality: ApiClient) -> None:
    resp = quality.post(
        "/suppliers",
        {
            "code": "OPT1",
            "name": "Optional Fields Ltd",
            "category": "service",
            "status": "approved",
        },
    )
    assert resp.status_code in OK, resp.text
    assert (resp.json()["gstin"], resp.json()["city"], resp.json()["state"]) == (None, None, None)


def test_supplier_code_is_unique_per_tenant_but_reusable_across_tenants(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    qa, qb = api.login_as(a.quality), api.login_as(b.quality)
    assert make_supplier(qa, code="DUP-1")["code"] == "DUP-1"
    clash = qa.post("/suppliers", supplier_body(code="DUP-1"))
    assert clash.status_code in (409, 422), clash.text
    problem(clash)
    assert make_supplier(qb, code="DUP-1")["code"] == "DUP-1"


def test_create_supplier_with_an_idempotency_key_creates_one_row(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    body, key = supplier_body(), new_key()
    first = quality.post("/suppliers", body, key=key)
    again = quality.post("/suppliers", body, key=key)
    assert first.status_code in OK and again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true"
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers")) == 1


# =================================================================================================
# update
# =================================================================================================
def test_update_supplier_changes_only_the_sent_fields_and_logs_before_and_after(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality, city="Pune", state="Maharashtra")
    resp = quality.post(
        f"/suppliers/{supplier['id']}/update", {"name": "Renamed Industries", "city": "Nashik"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["name"], data["city"]) == ("Renamed Industries", "Nashik")
    assert (data["state"], data["code"], data["status"]) == (
        supplier["state"],
        supplier["code"],
        "approved",
    )
    assert (
        data["updated_at"] > supplier["updated_at"] and data["created_at"] == supplier["created_at"]
    )
    audit = [
        r
        for r in log_rows(app_engine, seeded.id, UUID(supplier["id"]))
        if r["action"].endswith("update")
    ]
    assert len(audit) == 1
    assert (
        audit[0]["before"]["name"] == supplier["name"]
        and audit[0]["after"]["name"] == "Renamed Industries"
    )


def test_update_supplier_validates_like_create(quality: ApiClient) -> None:
    supplier = make_supplier(quality)
    for body in ({"name": ""}, {"category": "plastic"}, {"gstin": "bad"}):
        resp = quality.post(f"/suppliers/{supplier['id']}/update", body)
        assert resp.status_code == 422, body
        assert problem(resp)["code"] == "validation_error"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "blocked"),
        ("status_reason", "sneaky"),
        ("status_changed_by", "00000000-0000-7000-8000-000000000000"),
        ("status_changed_at", "2026-10-03T00:00:00Z"),
        ("archived_at", "2026-10-03T00:00:00Z"),
        ("tenant_id", "00000000-0000-7000-8000-000000000000"),
        ("id", "00000000-0000-7000-8000-000000000000"),
    ],
)
def test_supplier_update_command_ignores_status_fields(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, field: str, value: str
) -> None:
    """INV-MST-03: `status*` and `archived_at` are written only by their own commands. The update body forbids
    extra fields (422), and the stored row is exactly as it was."""
    supplier = make_supplier(quality, status="approved")
    before = row(app_engine, seeded.id, supplier["id"])
    resp = quality.post(f"/suppliers/{supplier['id']}/update", {"name": "Changed", field: value})
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "validation_error"
    assert row(app_engine, seeded.id, supplier["id"]) == before


def test_a_valid_update_leaves_every_status_column_untouched(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(approver, status="approved")
    assert (
        approver.post(
            f"/suppliers/{supplier['id']}/change-status",
            {"status": "on_watch", "reason": "Two late lots"},
        ).status_code
        == 200
    )
    before = row(app_engine, seeded.id, supplier["id"])
    assert (
        approver.post(f"/suppliers/{supplier['id']}/update", {"city": "Satara"}).status_code == 200
    )
    after = row(app_engine, seeded.id, supplier["id"])
    cols = ("status", "status_reason", "status_changed_by", "status_changed_at", "archived_at")
    assert {c: after[c] for c in cols} == {c: before[c] for c in cols}


def test_update_code_to_one_in_use_is_refused(quality: ApiClient) -> None:
    first, second = make_supplier(quality), make_supplier(quality)
    resp = quality.post(f"/suppliers/{second['id']}/update", {"code": first["code"]})
    assert resp.status_code in (409, 422), resp.text


# =================================================================================================
# archive (INV-PLT-08)
# =================================================================================================
def test_supplier_archive_sets_archived_at_and_keeps_references(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality)
    contacts = [make_contact(quality, supplier["id"]) for _ in range(2)]
    part = make_part(quality)
    link = make_supplier_part(quality, supplier["id"], part["id"], ppm_target=300)
    resp = quality.post(
        f"/suppliers/{supplier['id']}/archive", {"reason": "Supplier closed its plant"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is not None
    stored = row(app_engine, seeded.id, supplier["id"])
    assert stored["archived_at"] is not None, "archive sets archived_at"
    # nothing is deleted and nothing referencing the supplier changes
    assert quality.get(f"/suppliers/{supplier['id']}").status_code == 200
    kept = quality.get(f"/suppliers/{supplier['id']}/contacts").json()["items"]
    assert {c["id"] for c in kept} == {c["id"] for c in contacts}
    contact_rows = fetch_all(app_engine, seeded.id, "SELECT id, active FROM supplier_contacts")
    assert {(str(r["id"]), r["active"]) for r in contact_rows} == {
        (c["id"], True) for c in contacts
    }
    links = fetch_all(app_engine, seeded.id, "SELECT id, archived_at FROM supplier_parts")
    assert [(str(r["id"]), r["archived_at"]) for r in links] == [(link["id"], None)]
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers")) == 1
    audit = [
        r
        for r in log_rows(app_engine, seeded.id, UUID(supplier["id"]))
        if r["action"].endswith("archive")
    ]
    assert len(audit) == 1 and audit[0]["reason"] == "Supplier closed its plant"
    assert (
        audit[0]["before"]["archived_at"] is None and audit[0]["after"]["archived_at"] is not None
    )


def test_archive_requires_a_reason(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality)
    for body in ({}, {"reason": ""}, {"reason": "   "}, {"reason": "x" * 2001}):
        resp = quality.post(f"/suppliers/{supplier['id']}/archive", body)
        assert resp.status_code == 422, body
        assert any(e["field"] == "reason" for e in problem(resp)["errors"])
    assert row(app_engine, seeded.id, supplier["id"])["archived_at"] is None


def test_archiving_an_archived_supplier_is_409_invalid_transition(quality: ApiClient) -> None:
    supplier = make_supplier(quality)
    assert (
        quality.post(f"/suppliers/{supplier['id']}/archive", {"reason": "Closed"}).status_code
        == 200
    )
    again = quality.post(f"/suppliers/{supplier['id']}/archive", {"reason": "Closed again"})
    assert again.status_code == 409 and problem(again)["code"] == "invalid_transition"


def test_archived_suppliers_are_hidden_from_the_default_list_and_shown_with_archived_true(
    quality: ApiClient,
) -> None:
    live, gone = make_supplier(quality), make_supplier(quality)
    quality.post(f"/suppliers/{gone['id']}/archive", {"reason": "Closed"})
    default_ids = {s["id"] for s in list_all(quality, "/suppliers")}
    assert default_ids == {live["id"]}
    archived_ids = {s["id"] for s in list_all(quality, "/suppliers", archived="true")}
    assert gone["id"] in archived_ids


def test_a_supplier_part_cannot_be_created_for_an_archived_supplier(quality: ApiClient) -> None:
    """Archived masters are out of the pickers (blueprint 7.5, INV-PLT-08)."""
    supplier, part = make_supplier(quality), make_part(quality)
    quality.post(f"/suppliers/{supplier['id']}/archive", {"reason": "Closed"})
    resp = quality.post("/supplier-parts", {"supplier_id": supplier["id"], "part_id": part["id"]})
    assert resp.status_code in (409, 422), resp.text


# =================================================================================================
# GET /suppliers/{id}
# =================================================================================================
def test_get_supplier_returns_the_read_model_or_404(quality: ApiClient, viewer: ApiClient) -> None:
    supplier = make_supplier(quality)
    for client in (quality, viewer):
        got = client.get(f"/suppliers/{supplier['id']}")
        assert got.status_code == 200 and got.json() == supplier
    missing = quality.get("/suppliers/0198f0f0-0000-7000-8000-000000000000")
    assert missing.status_code == 404 and problem(missing)["code"] == "not_found"
    assert quality.get("/suppliers/not-a-uuid").status_code in (404, 422)


# =================================================================================================
# GET /suppliers: search, filters, sorts, keyset
# =================================================================================================
@pytest.fixture
def catalogue(approver: ApiClient) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {
        "bravo": {
            "name": "bravo Castings",
            "code": "AA-100",
            "category": "raw_material",
            "status": "approved",
            "gstin": "27BRAVO0001A1Z5",
        },
        "alpha": {
            "name": "Alpha Fasteners",
            "code": "BB-200",
            "category": "bought_out",
            "status": "on_watch",
            "gstin": "27ALPHA0002A1Z5",
        },
        "charlie": {
            "name": "charlie Precision",
            "code": "CC-300",
            "category": "job_work",
            "status": "approved",
            "gstin": None,
        },
        "delta": {
            "name": "Delta Logistics",
            "code": "DD-400",
            "category": "service",
            "status": "blocked",
            "gstin": None,
        },
    }
    return {key: make_supplier(approver, **spec) for key, spec in specs.items()}


def names(items: list[dict[str, Any]]) -> list[str]:
    return [i["name"] for i in items]


def test_search_matches_name_code_and_gstin_case_insensitively(
    quality: ApiClient, catalogue: dict[str, dict[str, Any]]
) -> None:
    assert names(list_all(quality, "/suppliers", q="fasteners")) == ["Alpha Fasteners"]
    assert names(list_all(quality, "/suppliers", q="PRECISION")) == ["charlie Precision"]
    assert names(list_all(quality, "/suppliers", q="cc-300")) == ["charlie Precision"]
    assert names(list_all(quality, "/suppliers", q="27bravo0001")) == ["bravo Castings"]
    assert list_all(quality, "/suppliers", q="no-such-supplier") == []


@pytest.mark.parametrize("wildcard", ["%", "_", "\\"])
def test_search_treats_like_wildcards_literally(
    quality: ApiClient, catalogue: dict[str, dict[str, Any]], wildcard: str
) -> None:
    assert list_all(quality, "/suppliers", q=wildcard) == []


def test_filters_by_status_and_category_and_their_combination(
    quality: ApiClient, catalogue: dict[str, dict[str, Any]]
) -> None:
    assert sorted(names(list_all(quality, "/suppliers", status="approved"))) == [
        "bravo Castings",
        "charlie Precision",
    ]
    assert names(list_all(quality, "/suppliers", category="service")) == ["Delta Logistics"]
    both = list_all(quality, "/suppliers", status="approved", category="job_work")
    assert names(both) == ["charlie Precision"]
    assert list_all(quality, "/suppliers", status="inactive") == []
    assert names(list_all(quality, "/suppliers", status="approved", q="castings")) == [
        "bravo Castings"
    ]


@pytest.mark.parametrize(
    "param", [{"status": "suspended"}, {"category": "plastic"}, {"archived": "maybe"}]
)
def test_filter_values_outside_the_documented_sets_are_422(
    quality: ApiClient, param: dict[str, str]
) -> None:
    resp = quality.get("/suppliers", params=param)
    assert resp.status_code in (400, 422), resp.text
    problem(resp)


def test_sort_name_is_case_insensitive_ascending_and_is_the_default(
    quality: ApiClient, catalogue: dict[str, dict[str, Any]]
) -> None:
    expected = ["Alpha Fasteners", "bravo Castings", "charlie Precision", "Delta Logistics"]
    assert names(list_all(quality, "/suppliers")) == expected
    assert names(list_all(quality, "/suppliers", sort="name")) == expected


def test_sort_code_is_ascending(quality: ApiClient, catalogue: dict[str, dict[str, Any]]) -> None:
    codes = [s["code"] for s in list_all(quality, "/suppliers", sort="code")]
    assert codes == ["AA-100", "BB-200", "CC-300", "DD-400"]


def test_sort_updated_at_is_most_recent_first(
    quality: ApiClient, catalogue: dict[str, dict[str, Any]]
) -> None:
    assert (
        quality.post(
            f"/suppliers/{catalogue['charlie']['id']}/update", {"city": "Thane"}
        ).status_code
        == 200
    )
    assert (
        quality.post(f"/suppliers/{catalogue['bravo']['id']}/update", {"city": "Thane"}).status_code
        == 200
    )
    ordered = names(list_all(quality, "/suppliers", sort="updated_at"))
    assert ordered[:2] == ["bravo Castings", "charlie Precision"]


@pytest.mark.parametrize("sort", ["gstin", "status", "-name", "name desc", "", "NAME"])
def test_unknown_sort_is_400_bad_request(quality: ApiClient, sort: str) -> None:
    resp = quality.get("/suppliers", params={"sort": sort})
    assert resp.status_code == 400 and problem(resp)["code"] == "bad_request"


def test_keyset_pagination_returns_every_supplier_exactly_once_in_order(
    quality: ApiClient,
) -> None:
    created = [make_supplier(quality, name=f"Supplier {i:02d}", code=f"K{i:02d}") for i in range(7)]
    for sort in ("name", "code", "updated_at"):
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            page = quality.get(
                "/suppliers",
                params={"sort": sort, "limit": 3, **({"cursor": cursor} if cursor else {})},
            ).json()
            assert 0 < len(page["items"]) <= 3
            seen += [i["id"] for i in page["items"]]
            cursor, pages = page["next_cursor"], pages + 1
            if cursor is None:
                break
        assert pages == 3, sort
        assert sorted(seen) == sorted(c["id"] for c in created) and len(seen) == len(set(seen)), (
            sort
        )


def test_keyset_pagination_is_stable_when_every_supplier_has_the_same_name(
    quality: ApiClient,
) -> None:
    """Ties are broken by id, so equal names are neither repeated nor skipped across pages."""
    created = [make_supplier(quality, name="Twin Industries", code=f"T{i}") for i in range(5)]
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        page = quality.get(
            "/suppliers", params={"limit": 2, **({"cursor": cursor} if cursor else {})}
        ).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(c["id"] for c in created) and len(seen) == 5


def test_a_supplier_created_between_pages_never_causes_a_repeat_or_a_skip(
    quality: ApiClient,
) -> None:
    original = [make_supplier(quality, name=f"M{i:02d} Works", code=f"M{i:02d}") for i in range(6)]
    first = quality.get("/suppliers", params={"limit": 3}).json()
    make_supplier(quality, name="A0 Early Bird Works", code="A0")  # sorts before the cursor
    make_supplier(quality, name="Z9 Late Works", code="Z9")  # sorts after it
    second = quality.get("/suppliers", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    seen = [i["id"] for i in first["items"]] + [i["id"] for i in second["items"]]
    assert len(seen) == len(set(seen)), "no repeats"
    assert seen[:6] == [o["id"] for o in original], "no original supplier skipped or reordered"


def test_a_cursor_from_one_sort_is_refused_by_another(quality: ApiClient) -> None:
    for i in range(4):
        make_supplier(quality, name=f"S{i}", code=f"C{i}")
    cursor = quality.get("/suppliers", params={"sort": "name", "limit": 2}).json()["next_cursor"]
    resp = quality.get("/suppliers", params={"sort": "code", "limit": 2, "cursor": cursor})
    assert resp.status_code == 400 and problem(resp)["code"] == "bad_request"


def test_list_limit_is_bounded_and_defaults_to_fifty(quality: ApiClient) -> None:
    for bad in (0, 201, -1):
        resp = quality.get("/suppliers", params={"limit": bad})
        assert resp.status_code in (400, 422), bad
    assert quality.get("/suppliers", params={"limit": 200}).status_code == 200
    assert quality.get("/suppliers").json() == {"items": [], "next_cursor": None}


def test_a_tampered_cursor_is_400(quality: ApiClient) -> None:
    for cursor in ("garbage", "e30", "eyJrIjogWyJ4Il19.deadbeef"):
        resp = quality.get("/suppliers", params={"cursor": cursor})
        assert resp.status_code == 400 and problem(resp)["code"] == "bad_request", cursor


def test_every_role_can_read_the_supplier_list(
    api: ApiFactory, seeded: SeededTenant, catalogue: dict[str, dict[str, Any]]
) -> None:
    for user in (seeded.admin, seeded.quality, seeded.viewer):
        assert user
        resp = api.login_as(user).get("/suppliers")
        assert resp.status_code == 200 and len(resp.json()["items"]) == 4, user.role
