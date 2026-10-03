"""Fixtures for the P02 import tests: an in-process `imports` worker and an `Importer` for the quality user."""

from collections.abc import Callable

import pytest

from tests.factories.api import ApiClient, ApiFactory
from tests.factories.db import SeededTenant
from tests.factories.imports import Importer


@pytest.fixture
def quality(api: ApiFactory, seeded: SeededTenant) -> ApiClient:
    assert seeded.quality
    return api.login_as(seeded.quality)


@pytest.fixture
def importer(quality: ApiClient, seeded: SeededTenant, drain: Callable[[], None]) -> Importer:
    return Importer(quality, seeded.id, drain)
