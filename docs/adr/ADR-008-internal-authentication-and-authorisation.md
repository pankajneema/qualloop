# ADR-008 — Internal authentication and authorisation

- Status: Proposed
- Spec: §2.2 (roles Admin / Quality / Viewer, `can_approve`), §6.1 users, §21.1 (argon2/bcrypt, login rate limits, secure sessions)

## Context
Internal users log in to the web app and phone PWA. The spec has no session table; PHASES P01 adds Google login and
password reset by email OTP (SPEC-GAP A-46 for Google).

## Options considered
| Option | Pros | Cons |
| --- | --- | --- |
| A. Stateless JWT in cookie | no store | no server-side revocation; deactivate user ≠ logout |
| B. **Opaque session token, server-side session in Redis** | instant revocation, small cookie, no new DB table | Redis outage logs users out |
| C. Session table in Postgres | durable | new table not in §6 |

## Decision
- Option B. Cookie `ql_session` = 32 random bytes (base64url), `HttpOnly; Secure; SameSite=Lax; Path=/`. Redis key
  `sess:{sha256(token)}` → `{session_id (UUIDv7), user_id, tenant_id, created_at, last_seen_at, ip, ua}`; idle timeout
  8 h, absolute 7 days (configurable). `session_id` is written to `activity_log.session_id`.
- Passwords: argon2id (`argon2-cffi`, library defaults), column `users.password_hash` (technical, A-74).
- Login rate limit: 5 failures / 15 min per email and per IP (Redis counters); generic error message.
- Password reset: 6-digit email OTP stored hashed in Redis, TTL 15 min, 5 attempts.
- Google login: **not built** until the human confirms A-46.
- CSRF: double-submit cookie `ql_csrf` + header `X-CSRF-Token`, plus `Origin` check.
- Authorisation: `core.permissions` evaluates per command: role ∈ allowed set, `can_approve` when flagged, plant scope
  (`plant_id ∈ users.plant_ids` for quality/viewer; admin all — A-04), actor type ≠ `ai`. Matrix in API.md §2–§3.
- Redis access (D-5): ElastiCache with TLS and RBAC. The app connects as ACL user `qualloop_app`, restricted to the key patterns `sess:*`, `user_sessions:*`, `otp:*`, `rl:*`, `idem:*`, `sched:*`, `dramatiq:*` and denied `@admin`, `@dangerous`, `FLUSHALL`, `KEYS` and `CONFIG`. The default user is disabled. The Redis security group accepts 6379 only from the ECS task security groups (ADR-019).
- Deactivating a user (`active=false`) deletes all their Redis sessions (index `user_sessions:{user_id}`).

## Consequences
- Redis loss → users re-login (acceptable; documented in runbook).
- Session store is shared by api replicas; no sticky sessions.

## Revisit when
- SSO/SAML requested by a paying customer (Part B §29), or
- Redis availability incidents cause > 1 forced logout per month (→ replica, S-02).
