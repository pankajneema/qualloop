"""argon2id password hashing with the library defaults (ADR-008, INV-SEC-04)."""

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


@lru_cache
def _hasher() -> PasswordHasher:
    return PasswordHasher()


@lru_cache
def _dummy_hash() -> str:
    """A valid argon2id hash of a random secret, verified against when there is no real hash (equal timing)."""
    return _hasher().hash("dummy-password-for-timing-equalisation")


def hash_password(plain: str) -> str:
    return _hasher().hash(plain)


def verify_password(stored_hash: str | None, plain: str) -> bool:
    """True iff `plain` matches `stored_hash`. Never raises.

    With no stored hash (unknown user, no password set) one verification against a dummy hash still runs, so the
    response time does not reveal whether the account exists."""
    target = stored_hash or _dummy_hash()
    try:
        ok = _hasher().verify(target, plain)
    except (VerificationError, InvalidHashError):
        return False
    return bool(ok) and bool(stored_hash)
