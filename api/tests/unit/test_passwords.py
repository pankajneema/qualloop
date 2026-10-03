"""ADR-008 / INV-SEC-04: argon2id with library defaults; unknown users still cost a verification."""

from typing import Any

import pytest

from tests.factories.contract import load
from tests.factories.env import KNOWN_HASH, PASSWORD


def test_hash_password_produces_an_argon2id_encoded_string() -> None:
    hashed = load("app.core.auth.passwords", "hash_password")(PASSWORD)
    assert hashed.startswith("$argon2id$v=19$")
    assert PASSWORD not in hashed


def test_hash_password_is_salted() -> None:
    hash_password = load("app.core.auth.passwords", "hash_password")
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_verify_password_accepts_the_right_password_and_rejects_others() -> None:
    verify = load("app.core.auth.passwords", "verify_password")
    assert verify(KNOWN_HASH, PASSWORD) is True
    assert verify(KNOWN_HASH, PASSWORD + "x") is False
    assert verify(KNOWN_HASH, "") is False


def test_verify_password_roundtrip_with_own_hash() -> None:
    mod = load("app.core.auth.passwords")
    assert mod.verify_password(
        mod.hash_password("another pass phrase 42"), "another pass phrase 42"
    )


@pytest.mark.parametrize(
    "bad_hash", ["", "plaintext", "$2b$12$abcdefghijklmnopqrstuv", "$argon2id$broken"]
)
def test_verify_password_on_malformed_hash_is_false_not_an_exception(bad_hash: str) -> None:
    assert load("app.core.auth.passwords", "verify_password")(bad_hash, PASSWORD) is False


def test_verify_password_with_no_stored_hash_still_runs_an_argon2_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timing is equalised with a dummy hash: a missing user/password costs the same as a wrong password."""
    argon2 = load("argon2")
    calls: list[Any] = []
    real = argon2.PasswordHasher.verify

    def spy(self: Any, hash_: str, password: str) -> bool:
        calls.append(hash_)
        return bool(real(self, hash_, password))

    monkeypatch.setattr(argon2.PasswordHasher, "verify", spy)
    assert load("app.core.auth.passwords", "verify_password")(None, PASSWORD) is False
    assert len(calls) == 1
    assert calls[0].startswith("$argon2id$")
