"""P02 helpers: master-data bodies and API creators. Everything goes through the public HTTP commands."""

import secrets
from typing import Any
from uuid import uuid4

import httpx

from tests.factories.api import ApiClient

OK = (200, 201)

CATEGORIES = ("raw_material", "bought_out", "job_work", "service")
STATUSES = ("approved", "approved_with_action_plan", "on_watch", "blocked", "inactive")


def token(n: int = 8) -> str:
    return uuid4().hex[:n].upper()


def gstin() -> str:
    """A valid 15-character GSTIN-shaped value ([0-9A-Z]{15}), unique enough per call."""
    return "27" + token(9) + "A1Z5"


def mobile() -> str:
    """A unique, valid E.164 Indian mobile."""
    return "+919" + "".join(secrets.choice("0123456789") for _ in range(9))


def supplier_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": f"S{token()}",
        "name": f"Supplier {token()} Industries",
        "category": "bought_out",
        "status": "approved",
        "city": "Pune",
        "state": "Maharashtra",
    }
    body.update(over)
    return {k: v for k, v in body.items() if v is not ...}


def make_supplier(client: ApiClient, **over: Any) -> dict[str, Any]:
    resp = client.post("/suppliers", supplier_body(**over))
    assert resp.status_code in OK, resp.text
    data: dict[str, Any] = resp.json()
    return data


def contact_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"Contact {token(4)}",
        "role": "Quality head",
        "mobile": mobile(),
        "email": f"contact.{uuid4().hex[:10]}@supplier.example.test",
    }
    body.update(over)
    return {k: v for k, v in body.items() if v is not ...}


def make_contact(client: ApiClient, supplier_id: str, **over: Any) -> dict[str, Any]:
    resp = client.post(f"/suppliers/{supplier_id}/contacts", contact_body(**over))
    assert resp.status_code in OK, resp.text
    data: dict[str, Any] = resp.json()
    return data


def part_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "part_no": f"P-{token()}",
        "name": f"Bracket {token(4)}",
        "category": "Fasteners",
        "current_revision": "A",
    }
    body.update(over)
    return {k: v for k, v in body.items() if v is not ...}


def make_part(client: ApiClient, **over: Any) -> dict[str, Any]:
    resp = client.post("/parts", part_body(**over))
    assert resp.status_code in OK, resp.text
    data: dict[str, Any] = resp.json()
    return data


def make_customer(client: ApiClient, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"name": f"OEM {token(4)}", "code": f"C{token()}"}
    body.update(over)
    resp = client.post("/customers", body)
    assert resp.status_code in OK, resp.text
    data: dict[str, Any] = resp.json()
    return data


def make_supplier_part(
    client: ApiClient, supplier_id: str, part_id: str, **over: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {"supplier_id": supplier_id, "part_id": part_id}
    body.update(over)
    resp = client.post("/supplier-parts", body)
    assert resp.status_code in OK, resp.text
    data: dict[str, Any] = resp.json()
    return data


def list_all(client: ApiClient, path: str, **params: Any) -> list[dict[str, Any]]:
    """Follow the keyset cursor to the end (limit 200 pages)."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(1000):
        query = {"limit": 200, **params, **({"cursor": cursor} if cursor else {})}
        resp: httpx.Response = client.get(path, params=query)
        assert resp.status_code == 200, f"GET {path}: {resp.status_code} {resp.text}"
        page = resp.json()
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError(f"{path}: pagination never terminated")
