# Changelog

One section per verified phase: what users can now do, notable decisions, known limitations.

## P00 — Architecture & scaffold (2026-10-03, tag `p00-verified`)

**Now possible:** `make up` starts Postgres 16, Redis, MinIO, Mailpit, the API (`/healthz`, `/readyz`) and the
web app shell (QualLoop, en/hi, design tokens). `make lint`, `make test`, `make ci`, `make e2e` run locally.

**Decisions:** modular monolith (§22.1 modules, import-linter); forced Postgres RLS with deny-by-default for
supplier sessions; UUIDv7, money as BIGINT paise, UTC timestamps, plant-timezone periods; single command
pipeline writing activity_log + outbox in one transaction; Dramatiq + APScheduler; SQL as-of metrics engine;
AWS Mumbai + Terraform proposed. 19 ADRs in `docs/adr/`; architecture in `docs/architecture/`.

**Known limitations / open:** no business tables or endpoints yet (P01+). `.env.example` missing (blocked by the
`.env*` permission rule). GitHub Actions never executed (no remote); CI verified locally only. Paid services
(AWS, SES, WhatsApp, Bedrock/Textract, Sentry), virus scanner choice (A-47), Google login (A-46), billing (A-48),
minio dev image and extra technical tables/columns still await explicit human decisions. 90 SPEC-GAPs open in
`docs/build/OPEN_QUESTIONS.md`.
