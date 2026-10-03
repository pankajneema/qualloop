"""Assertions on database errors by psycopg error class (SQLSTATE) and message."""

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import DBAPIError


@contextmanager
def expect_db_error(exc_type: type[BaseException], match: str | None = None) -> Iterator[None]:
    with pytest.raises(DBAPIError) as excinfo:
        yield
    orig = excinfo.value.orig
    assert isinstance(orig, exc_type), (
        f"expected {exc_type.__name__}, got {type(orig).__name__}: {orig}"
    )
    if match is not None:
        assert re.search(match, str(orig), re.IGNORECASE), f"{match!r} not in {orig}"
