"""Fixtures for the P02 masters tests: one logged-in client per role of the seeded tenant."""

import pytest

from tests.factories.api import ApiClient, ApiFactory
from tests.factories.db import SeededTenant


@pytest.fixture
def quality(api: ApiFactory, seeded: SeededTenant) -> ApiClient:
    assert seeded.quality
    return api.login_as(seeded.quality)


@pytest.fixture
def approver(api: ApiFactory, seeded: SeededTenant) -> ApiClient:
    """Quality role with can_approve (the Head of Quality)."""
    assert seeded.approver
    return api.login_as(seeded.approver)


@pytest.fixture
def admin(api: ApiFactory, seeded: SeededTenant) -> ApiClient:
    assert seeded.admin
    return api.login_as(seeded.admin)


@pytest.fixture
def viewer(api: ApiFactory, seeded: SeededTenant) -> ApiClient:
    assert seeded.viewer
    return api.login_as(seeded.viewer)
