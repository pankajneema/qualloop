"""Test infrastructure: connections to the dev stack use IPv4 literals, never `localhost` (TCP self-connect flake).

On macOS the host ports of the dev stack (e.g. 55432, 56379) lie in the ephemeral source-port range and the stack
listens on IPv4 only, while `localhost` resolves to `::1` first. A connect to `::1:<port>` can then be answered by
the connecting socket itself (same source and destination port), and redis-py fails with "Invalid Database"."""

import pytest

from tests.factories.env import pin_loopback


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "redis://qualloop_app:pw@localhost:56379/0",
            "redis://qualloop_app:pw@127.0.0.1:56379/0",
        ),
        (
            "postgresql+psycopg://u:p@localhost:55432/qualloop_test",
            "postgresql+psycopg://u:p@127.0.0.1:55432/qualloop_test",
        ),
        ("redis://localhost/3", "redis://127.0.0.1/3"),
        ("redis://LOCALHOST:6379/0", "redis://127.0.0.1:6379/0"),
    ],
)
def test_localhost_in_a_stack_url_is_pinned_to_the_ipv4_loopback_literal(
    url: str, expected: str
) -> None:
    assert pin_loopback(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "redis://u:p@redis:6379/0",
        "redis://u:p@127.0.0.1:56379/15",
        "postgresql+psycopg://u:p@db.internal:5432/x",
        "redis://u:p@localhost.example.com:6379/0",
    ],
)
def test_other_hosts_are_left_untouched(url: str) -> None:
    assert pin_loopback(url) == url


def test_the_test_session_connects_to_the_stack_through_ip_literals(
    settings: object,
) -> None:
    import os
    from urllib.parse import urlsplit

    for name in (
        "QL_REDIS_URL",
        "QL_DATABASE_URL",
        "QL_TEST_DATABASE_URL",
        "QL_TEST_DATABASE_URL_OWNER",
    ):
        value = os.environ.get(name)
        if value:
            assert urlsplit(value).hostname != "localhost", f"{name} still names localhost"
