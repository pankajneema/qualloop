---
description: Phase 0 - design the complete architecture and scaffold the repo, then stop for human approval
---

Run **Phase 0 — Architecture & Scaffold** exactly as described in `docs/build/PHASES.md` (section P00).

Steps:
1. Read `CLAUDE.md`, the whole blueprint `docs/blueprint/Supplier_Quality_OS_Blueprint_FINAL.md`,
   `docs/build/PHASES.md` and `docs/design/DESIGN_SPEC.md`.
2. Write `docs/understanding.md` yourself: the control loop in your words, every entity and state machine,
   every invariant with its §, and every ambiguity you found (do not resolve silently).
3. Delegate to the `architect` subagent with a self-contained brief to produce all Phase 0 architecture
   documents and ADRs listed in its instructions.
4. Delegate to the `devops-engineer` subagent to scaffold the repo per `docs/architecture/REPO_LAYOUT.md`:
   monorepo, docker compose, Makefile, CI pipeline, lint/type/test tooling, health endpoints, logging,
   Alembic baseline with the RLS helper, `web` app shell with design tokens from DESIGN_SPEC.md.
5. Delegate to `security-reviewer` and `code-reviewer` (in parallel) to review the architecture docs and scaffold.
   Fix or record findings.
6. Delegate to `verifier` to check the P00 gate.
7. Commit using CLAUDE.md §4:
   ```
   git add -A
   git commit -m "docs(p00): architecture, ADRs and repo scaffold"
   ```
8. STOP. Present to the human: architecture summary (1 page), ADR list with one-line decisions,
   scaling stages, the ambiguity list, verification result. Ask for approval.
   After approval: `git tag p00-verified` and update `docs/build/STATUS.md`.
