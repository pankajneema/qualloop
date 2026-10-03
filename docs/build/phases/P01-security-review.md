# P01 — Security review record

- Reviewer: `security-reviewer` subagent (read-only), fresh context
- Pass 1: diff `9ed6627..94b8616`. Result: 0 Critical, **1 High**, 3 Medium, 7 Low. All fixed or recorded in `8de9d23` (see below).
- Pass 2 (re-review): HEAD `8de9d236dbe7736f757a18127b708a7b4eb8211d`, diff `9ed6627..HEAD`. Code read and live stack probed (api, web, Postgres dev DB, Redis, SeaweedFS, ClamAV, Mailpit); pytest not run.

## Pass 2 — severity open at `8de9d23`

| Critical | High | Medium | Low | Info |
|---|---|---|---|---|
| 0 | 0 | 1 | 4 | 8 |

**Gate statement (reviewer):** "No open Critical/High at 8de9d236dbe7736f757a18127b708a7b4eb8211d (1 Medium, 4 Low, 8 Info open)."

## Pass 1 findings and their status at pass 2

| # | Pass 1 finding | Sev | Status at `8de9d23` (reviewer evidence) |
|---|---|---|---|
| H-1 | The per-IP login limit counted the proxy IP, so anyone could lock out every user | High | **Fixed.** XFF is trusted only from a peer in `QL_TRUSTED_PROXIES`; uvicorn and gunicorn proxy rewriting is off; a bogus CIDR is rejected at startup. Residual config Low: L-1 |
| M-1 | Concurrent logins bypassed the 5-failure limit | Medium | **Fixed.** Atomic MULTI before argon2. Live: 30 parallel → 5×401, 25×429 |
| M-2 | `QL_ENV` defaulted to local | Medium | **Fixed.** Required `Literal`; production rejects dev secrets. Residual Low: L-2 |
| M-3 | Runtime held the owner DB URL | Medium | **Fixed.** `QL_DATABASE_URL_OWNER` appears 0 times in the api, worker, dispatcher and scheduler env; read only by `alembic/env.py` |
| L-1 | Supplier-session insert policy is `OR true` on audit and outbox | Low | Open → A-102 (P05; no supplier actor exists yet) |
| L-2 | OTP guess budget was unbounded over time | Low | **Fixed** (per-IP and per-account caps, atomic OTP). The design introduced pass-2 M-1 |
| L-3 | Bound parameters appeared in error text | Low | **Fixed** (`hide_parameters=True` plus `mask_text` on `last_error` and tracebacks) |
| L-4 | `users` UPDATE grant was table-wide | Low | **Fixed** (column-level grant) |
| L-5 | Redis app user could FUNCTION/SCRIPT FLUSH | Low | **Fixed.** Live: NOPERM |
| L-6 | Cookies have no `__Host-` prefix | Low | Open → A-101 (human decision) |
| L-7 | Cross-tenant email-existence check via 409 | Low | Open → A-103 (consequence of A-03) |
| Info | CI checkout persisted credentials | Info | **Fixed** (11/11 `persist-credentials: false`) |

## Pass 2 — open findings

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| M-1 | Medium | The reset-confirm account cap (A-105) counts failures before checking a code exists, so 10 junk confirms block the victim's recovery for 24 h | Fixed in fix loop 1 (see addendum) |
| L-1 | Low | Local compose trusts the Docker gateway `172.29.0.0/24`, so XFF is spoofable in dev; nothing rejects an over-broad production CIDR | Recorded for P09 (A-106); dev only |
| L-2 | Low | Production settings check matches exact default strings only (owner user in `database_url`, dev Redis password, localhost base URL, `0.0.0.0/0` proxies all accepted) | Recorded for P09 hardening (A-107) |
| L-3 | Low | `plants` and `idempotency_keys` allow UPDATE on every column | Fixed in fix loop 1 (see addendum) |
| L-4 | Low | User audit snapshots store the email unmasked in append-only `activity_log` (ADR-019 masks contact PII) | Recorded for the human (A-108) |
| I-1..I-8 | Info | `__Host-` prefix (A-101); supplier insert policy (A-102); cross-tenant 409 (A-103); login/reset race on password version; Redis SCAN/EVAL operational note; CSP vs presigned S3 host (P03/P04); `/healthz` version exposure (P09); negligible login timing difference | Tracked; no gate impact |

## Checked OK (pass 2, summarised from reviewer evidence)

RLS ENABLE and FORCE on all 7 tables, with fail-closed behaviour when no GUC is set. Cross-tenant insert, select and update are refused live, and API IDOR probes return 404. Definer functions are owned by `qualloop_sysfn` with a safe search_path and EXECUTE granted to the app role only. All 15 routes except public auth require `require(...)`. Role and flags are reloaded on every request. Session cookies are HttpOnly, Secure and SameSite=lax, with no fixation and a sha256-keyed store. CSRF and Origin are enforced. Idempotency is scoped per tenant, actor and key, and keys must be UUIDs. Bodies use `extra=forbid` and strict ints, and 413 applies to both sized and chunked bodies. Presigned PUTs are signed over length, type and host with a 900 s expiry, and the buckets are private. Download checks the tenant prefix and refuses traversal. ClamAV is fail-closed. Error bodies follow RFC 9457 with no internals, and logs carry no unmasked emails. Dispatcher and jobs keep per-tenant context. gitleaks, pip-audit and pnpm audit are clean. CI uses `contents: read`.

Probe leftovers in the dev DB: two append-only `auth.login` audit rows for demo users, removed by `make down V=1`.

## Addendum: fix loop 1

- **M-1 fixed.** Reset confirm returns the generic 422 without touching the per-account cap when no live code exists. The cap slot is reserved atomically only when a guess is made against a live code. Regression tests are in `integration/auth/test_password_reset_hardening.py` §(c): `test_junk_confirms_with_no_code_issued_do_not_block_the_later_real_code`, `test_ten_wrong_guesses_against_a_live_code_still_block_a_later_fresh_valid_code` and `test_confirm_with_no_live_code_answers_the_same_generic_422_as_a_wrong_code`.
- **L-3 fixed.** Column-level UPDATE grants now apply to `plants` (`name, address, timezone, updated_*`) and `idempotency_keys` (`response_status, response_body, updated_*`). Regression tests are in `integration/db/test_users_grants_and_error_leaks.py`.
- Fresh-volume run after the fix: `make test-api` → 879 passed, 19 xfailed. Coverage is 90.95% overall and 93% on `app/core`. `make lint-api`, `make migrations-roundtrip` and `make lint-ci` all exit 0.
- Open at this point: 0 Critical, 0 High, 0 Medium. Lows L-1, L-2 and L-4 are recorded as A-106, A-107 and A-108.
