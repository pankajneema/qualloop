"""API.md 1.6: `Idempotency-Key` is a client UUID. Anything else is a 422 `validation_error` on the header field,
and nothing is written."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows
from tests.integration.commands.test_platform_commands_api import admin_client, new_plant_body

pytestmark = pytest.mark.integration

NOT_UUIDS = [
    "not-a-uuid",
    "12345",
    "abc",
    "0123456789abcdef0123456789abcdefx",
    "00000000-0000-0000-0000-00000000000g",
    str(uuid4()) + "-extra",
    "{" + str(uuid4()) + "}",
    "x" * 300,
]


@pytest.mark.parametrize("key", NOT_UUIDS, ids=[f"bad-{i}" for i in range(len(NOT_UUIDS))])
def test_a_non_uuid_idempotency_key_is_a_422_validation_error_on_the_header_field(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None, key: str
) -> None:
    admin = admin_client(api, seeded)
    body = new_plant_body()
    resp = admin.post("/plants", body, key=key)
    assert resp.status_code == 422, resp.text
    problem_body = problem(resp)
    assert problem_body["code"] == "validation_error"
    assert "Idempotency-Key" in {e["field"] for e in problem_body["errors"]}
    assert (
        fetch_all(
            app_engine, seeded.id, "SELECT 1 FROM plants WHERE code = :c", {"c": body["code"]}
        )
        == []
    )
    assert [r for r in log_rows(app_engine, seeded.id) if r["object_type"] == "plant"] == []
    assert outbox_rows(app_engine, seeded.id) == []
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM idempotency_keys") == []


def test_a_viewer_with_a_bad_idempotency_key_still_gets_403_because_authorisation_comes_first(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    """A viewer is still told 403 (authorisation precedes input validation, API.md 1.4), not 422."""
    assert seeded.viewer
    resp = api.login_as(seeded.viewer).post("/plants", new_plant_body(), key="not-a-uuid")
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "make_key",
    [
        lambda: str(uuid4()),
        lambda: str(uuid4()).upper(),
        lambda: str(UUID(int=0x01890000000070008000000000000001)),
    ],
    ids=["lowercase-v4", "uppercase-v4", "v7-shaped"],
)
def test_a_uuid_idempotency_key_is_accepted_in_any_case(
    api: ApiFactory, seeded: SeededTenant, make_key: Callable[[], str]
) -> None:
    admin = admin_client(api, seeded)
    resp = admin.post("/plants", new_plant_body(), key=make_key())
    assert resp.status_code in (200, 201), resp.text


def test_a_valid_key_still_replays(api: ApiFactory, seeded: SeededTenant) -> None:
    admin = admin_client(api, seeded)
    body, key = new_plant_body(), new_key()
    first = admin.post("/plants", body, key=key)
    again = admin.post("/plants", body, key=key)
    assert again.headers["idempotency-replayed"] == "true" and again.json() == first.json()
