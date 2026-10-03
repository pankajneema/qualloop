# P01 — Code review record

- Reviewer: `code-reviewer` subagent (read-only). Reviewed diff `9ed6627..94b8616`.
- Reviewer run: `make test-api` gave 746 passed, 19 xfailed; `app/core` 93%; `make lint-api` green.
- Result: 0 Blocker, 0 Critical, 3 High, 5 Medium, 14 Low.
- Every High and Medium is fixed in `8de9d23 fix(p01): address review findings`, each with a regression test written first by `qa-engineer`. The test names are in `P01-tests.md` §"Review regressions".

| ID | Sev | Finding | Disposition |
| --- | --- | --- | --- |
| H1 | High | The outbox dispatcher's default enqueue called `broker.get_actor`. That raises `ActorNotFound` in the dispatcher process, so every handled event would dead-letter. | Fixed. Handlers are registered by name and queue, and the message is built without `get_actor`. Regression: `integration/outbox/test_dispatcher_default_enqueue.py` |
| H2 | High | The login rate limit was check-then-record, so concurrent guesses bypassed the 5-failure limit. | Fixed. The attempt is reserved atomically before argon2. Regression: `test_ten_concurrent_wrong_password_logins_cannot_exceed_the_five_failure_limit` |
| H3 | High | Session refresh used an unconditional SET, so it could resurrect a deleted session after logout or reset. | Fixed (`SET … XX`). Regression: `integration/auth/test_session_resurrection.py` |
| M1 | Medium | The last-admin guard (A-98) was untested. | Tests added: `integration/commands/test_last_admin_guard.py` |
| M2 | Medium | The "can_approve required" mandatory test was vacuous. | Pipeline test added: `integration/commands/test_can_approve_pipeline.py` |
| M3 | Medium | argon2, Redis and SMTP calls ran inside open DB transactions. | Fixed for login, reset confirm and the reset email job (`own_transaction` jobs) |
| M4 | Medium | Client IP was the socket peer behind a proxy. | Fixed with `QL_TRUSTED_PROXIES` (A-106). Regression: `integration/auth/test_client_ip_and_login_race.py` |
| M5 | Medium | ADR deviations (retry count, `uuid6`) were not recorded. | Recorded as A-100 and A-99 for the human gate |
| L1 | Low | A chunked body over 1 MB returned 400, not 413. | Fixed. Regression: `integration/errors/test_chunked_body_limit.py` |
| L2 | Low | Outbox delivery is at-least-once, not exactly-once. | Documented in the dispatcher (consumers dedupe on `event_id`). Each row now runs in its own SAVEPOINT |
| L3 | Low | UUIDv7 ordering broke after counter overflow or a clock step back. | Fixed (bounded clamp). Regression in `unit/test_core_primitives.py` |
| L4 | Low | The scanner downloaded objects without checking their size. | Fixed (`too_large`). Regression: `integration/files/test_scan_size_limit.py` |
| L5 | Low | The `Idempotency-Key` format was not validated. | Fixed (UUID, otherwise 422). Regression: `integration/commands/test_idempotency_key_format.py` |
| L6 | Low | Dead branch in idempotency. | Replaced with an assertion |
| L7 | Low | A hidden import cycle went around the import linter. | Removed. The router imports the command modules explicitly |
| L8 | Low | Concurrent pytest runs interfered with each other, and leaked threads kept pytest alive. | Fixed in `conftest.py` (advisory lock, thread cleanup) |
| L9 | Low | A redelivered old reset job could overwrite a newer OTP. | Fixed (nonce compare-and-set). Regression in `integration/auth/test_password_reset_hardening.py` |
| L10 | Low | OTP consume was non-atomic and could leave a stray key. | Fixed (MULTI with `EXPIRE NX`) |
| L11 | Low | A reset request leaked email existence when enqueue failed. | Fixed (always 202) |
| L12 | Low | No metric for job dead letters. | Fixed: `qualloop_jobs_dead_lettered_total` |
| L13 | Low | Unmasked tracebacks were stored in Redis messages. | Fixed (`TracebackMask` middleware) |
| L14 | Low | The hook bus was untested. | Tests added: `integration/commands/test_hook_bus.py` |

Orchestrator note: the `feat(p01)` commit includes test-side corrections that the orchestrator approved during the build. They are: unique emails per run, the Mailpit query encoding, Redis `protocol=2` for the NOAUTH check, and accepting "DEBUG command not allowed" as a DEBUG denial (so Redis keeps DEBUG disabled). No assertion was weakened.
