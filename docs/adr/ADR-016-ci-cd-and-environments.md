# ADR-016 — CI/CD and environments

- Status: Accepted (2026-10-03, design only); still pending — CI host (GitHub Actions) assumes a GitHub remote; the repo currently has none → **human to confirm**
- Spec: §21.2 (security tests in CI), §24.1, CLAUDE.md §3–§5 (gates; no prod without approval), PHASES P00/P09

## Options considered
| Concern | Options | Chosen |
| --- | --- | --- |
| CI | **GitHub Actions**, GitLab CI, Buildkite | GitHub Actions (service containers for Postgres/Redis/MinIO; OIDC to AWS for deploys) |
| Deploy target | ECS rolling via CI; CodeDeploy blue/green | **ECS rolling update with circuit-breaker rollback** (Stage 1) |
| Migrations | at app start; **one-off task before rollout** | one-off ECS task as `qualloop_owner` |
| Branching | GitFlow; **trunk-based** with short-lived branches | trunk-based; `main` always deployable to staging |

## Decision
| Environment | Purpose | Deploy | Data |
| --- | --- | --- | --- |
| local | development | `make up` | seed |
| CI | verification | every push/PR | factories |
| staging | integration with provider sandboxes, demo, restore drills | auto on merge to `main` | synthetic + seed; never real customer data |
| prod | customers | tag `vX.Y.Z` → GitHub Environment with **required human reviewer** | customer data |

Pipeline (REPO_LAYOUT.md §7): lint → types → unit → integration (real Postgres 16, RLS as `qualloop_app`) → migrations
up/down/up → security tests (§21.2) → coverage gates (≥ 90% finance, receipts/defect events, scoring, risk, scar,
documents; ≥ 75% overall — CLAUDE.md §6) → image build → (main) Playwright E2E → (main) push images to ECR, deploy staging.

Migration policy (zero-downtime, P09): expand/contract — additive migration deployed first; code using it next;
destructive step in a later release; destructive or data-rewriting migrations after a pilot exists need human approval
(CLAUDE.md §5). Every migration has a tested `downgrade`.

Supply chain (S-1):
- Third-party GitHub Actions are pinned by **full commit SHA**, not by tag.
- Each workflow declares minimal `permissions:` (default `contents: read`; `id-token: write` only in deploy).
- No `pull_request_target`.
- A scheduled weekly **audit job** (`security-audit.yml`) runs `pip-audit`, `pnpm audit --prod`, Trivy on the latest images and gitleaks on full history. Findings open an issue, and High/Critical findings block the next deploy.

Other controls: `uv sync --frozen`, `pnpm install --frozen-lockfile`, pinned base images by digest, Trivy scan,
pip-audit, pnpm audit, gitleaks; Dependabot/Renovate weekly (human merges).

## Consequences
- The verifier agent can reproduce CI locally with `make lint && make test`.
- Prod deploys are always explicit human actions.

## Revisit when
- CI wall time > 15 min (→ split jobs, test sharding), or
- a failed deploy causes > 5 min user-visible downtime (→ blue/green).
