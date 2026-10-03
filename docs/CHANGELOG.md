# Changelog

One section per verified phase: what users can now do, notable decisions, known limitations.

## P00 — Architecture & scaffold (2026-10-03, tag `p00-verified`)

**Now possible:** `make up` starts Postgres 16, Redis, MinIO, Mailpit, the API (`/healthz`, `/readyz`) and the
web app shell (QualLoop, en/hi, design tokens). `make lint`, `make test`, `make ci`, `make e2e` run locally.

**Decisions:** modular monolith (§22.1 modules, import-linter); forced Postgres RLS with deny-by-default for
supplier sessions; UUIDv7, money as BIGINT paise, UTC timestamps, plant-timezone periods; single command
pipeline writing activity_log + outbox in one transaction; Dramatiq + APScheduler; SQL as-of metrics engine;
AWS Mumbai + Terraform proposed. 20 ADRs in `docs/adr/`; architecture in `docs/architecture/`.

**Follow-up fixes (2026-10-03):**
- Added `.env.example`. The `.env*` read-deny rule was narrowed to real env files so the template can exist.
- Local and CI object storage moved from the unmaintained `bitnamilegacy/minio` to SeaweedFS (ADR-020).
- Added a commit-msg guard (`infra/scripts/check_commit_msg.sh`) that rejects trailers, sign-offs and multi-line messages.
- `ruff format` replaces black (CLAUDE.md, backend agent, ADR-002).

**Decisions recorded:**
- No paid services for now. Production targets are AWS ap-south-1, SES, the WhatsApp Cloud API, the Sentry free
  tier and Bedrock/Textract; no accounts are opened until needed.
- ClamAV is the virus scanner.
- `amount_paise` is approved.
- The technical tables and columns in DATA_MODEL.md are approved.
- Google login moves to R1.1.
- Billing stays in P09.

**Known limitations / open:**
- No business tables or endpoints yet (P01+).
- GitHub Actions has not run yet; CI is verified locally only.
- The CI host still needs confirmation (ADR-016).
- 80 SPEC-GAPs remain open in `docs/build/OPEN_QUESTIONS.md`.
