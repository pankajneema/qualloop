# ADR-019 — Security baseline and secrets

- Status: Accepted (2026-10-03)
- Spec: §21.1 controls, §21.2 CI security tests, §21.5 DPDP Act 2023, §21.6 (later roadmap — not built in R1)

## Decision — controls mapped to §21.1
| §21.1 control | Implementation |
| --- | --- |
| TLS | ACM certs on CloudFront/ALB; TLS 1.2+; HSTS (1 year, includeSubDomains); internal: RDS `force_ssl`, Redis TLS |
| Encryption at rest | RDS/ElastiCache/S3/EBS with KMS CMKs per environment |
| Postgres RLS + app authorisation | ADR-004, ADR-008 |
| argon2/bcrypt passwords | argon2id (ADR-008) |
| Login rate limits | ADR-008; WAF rate rules as outer layer |
| Secure sessions | opaque tokens, HttpOnly/Secure/SameSite cookies, CSRF double-submit, idle + absolute timeouts |
| Private buckets, signed URLs ≤ 15 min | ADR-011 |
| Content-type and size validation, virus scanning | ADR-011 (ClamAV pending approval, A-47) |
| Audit logging with before/after, reason, session, IP | ADR-003 |
| Daily encrypted backups | ADR-018 |

Additional baseline (OWASP ASVS L2 as the checklist used by `security-reviewer`):
| Area | Rule |
| --- | --- |
| Headers | CSP (`default-src 'self'`; images from S3 presigned origin; no inline scripts except Next nonce), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` (`no-referrer` on supplier pages), `Permissions-Policy` (camera only on capture/supplier upload pages), `frame-ancestors 'none'` |
| Input | Pydantic strict models; size limits on JSON bodies (1 MB); SQL only via SQLAlchemy bound parameters; no raw string SQL with user input |
| Output | React escaping; supplier text never rendered as HTML; Excel formula neutralisation (ADR-014) |
| SSRF | no server-side fetch of user-supplied URLs in R1; provider endpoints allow-listed in config |
| Errors | problem+json without stack traces or SQL; `request_id` only |
| Definer functions | fixed list (DATA_MODEL.md §8), `SET search_path`, return ids only, reviewed by security-reviewer |
| Dependencies | pip-audit, pnpm audit, Trivy in CI on every PR plus the weekly scheduled audit job; GitHub Actions pinned by commit SHA with minimal `permissions:` (S-1, ADR-016); weekly update PRs |
| Redis (D-5) | TLS in transit; RBAC/ACL least-privilege user `qualloop_app` (key patterns and command categories restricted, default user disabled, AUTH required); security group ingress only from ECS task SGs; no public endpoint; local compose uses `requirepass` + ACL file |
| Supplier token handling (D-4) | token exchanged to HttpOnly cookie at first request; `/s/*` not logged at edge or app (ADR-009) |
| AI prompt injection (D-8) | ADR-012 item 9 |
| Cross-border transfers (D-8) | any processor outside India (e.g. Sentry) requires human/legal approval under DPDP §21.5 before enabling |

## Secrets
| Environment | Store | Access |
| --- | --- | --- |
| local | `.env` (gitignored), values from `.env.example` placeholders | developer |
| CI | GitHub Actions secrets (only for deploy OIDC role ARNs); tests use throwaway local values | workflow |
| staging/prod | AWS Secrets Manager (DB passwords per role, session secret, HMAC secret, provider API keys), injected as ECS task secrets; KMS-encrypted | task role least privilege |

Rules: no secret in git (gitleaks pre-commit + CI); `.env` unreadable by agents (`.claude/settings.json`); rotation
procedure in `docs/runbooks/rotate-secrets.md` (P09) — session/HMAC secrets support two active keys (current + previous)
so rotation does not log everyone out; DB passwords rotated via Secrets Manager rotation for `qualloop_app`.

## Personal data (§21.5, DPDP Act 2023)
| Requirement | Implementation |
| --- | --- |
| Privacy notice | shown on supplier link page before OTP (text to be supplied by the human/legal) |
| Recorded consent per channel | `contact_consents` (ADR-010) |
| Purpose limitation | contact data used only for quality workflow notifications; never sent to AI providers |
| Contact deactivation | `POST /contacts/{id}/disable` |
| Anonymisation on request | `POST /contacts/{id}/anonymise` (Admin): replaces name with placeholder, nulls mobile/email, redacts them in `messages.variables`; quality records retained. To limit PII in the append-only `activity_log`, audit before/after for contacts stores mobile/email **masked** from the start (`+91******3210`); the contact name in historic audit rows is not rewritten (append-only). Whether that is acceptable is part of the legal review (A-83) |
| Retention | keep everything until legal review (A-83); no compliance claims (§21.5) |
| PII in logs | masked (ADR-015) |

## Consequences
- `security-reviewer` checks each phase against this table and §21.2 tests.
- Anonymisation vs append-only audit tension is explicitly recorded for legal review.

## Revisit when
- First enterprise security questionnaire or pen-test (§21.6), or any Critical/High finding recurs in two phases.
