---
description: Build one phase end to end with tests-first, reviews, independent verification, fix loop, human gate and commits. Usage - /build-phase 3
argument-hint: <phase number, e.g. 3>
---

Build **Phase $ARGUMENTS** following CLAUDE.md §3 exactly. Pad the phase number to two digits (P03).

0. Preconditions — check and report before doing anything:
   - Previous phase is tagged `p<prev>-verified` and STATUS.md shows it approved. If not, STOP.
   - Working tree is clean (`git status`). If not, STOP and ask.

1. Plan (you): read the phase in `docs/build/PHASES.md`, every § it lists, and the relevant ADRs.
   Write `docs/build/phases/P$ARGUMENTS-plan.md` (scope, tables, commands, endpoints, screens, invariants,
   edge cases, test list, which subagent does what, risks). Show the human a 10-line summary. Continue
   unless the plan contains a SPEC-GAP that changes scope — then STOP and ask.

2. Tests first: brief `qa-engineer` (self-contained: phase, § list, contracts in docs/architecture, the
   mandatory cases from PHASES.md). Run the tests; confirm they fail for the expected reason.
   ```
   git add -A
   git commit -m "test(p$ARGUMENTS): failing tests for <phase name>"
   ```

3. Build: brief `backend-engineer`, `data-engineer` and/or `frontend-engineer` per the plan (parallel only
   when files don't overlap). Integrate. Run full suite + lint + types + migrations up/down/up.
   ```
   git add -A
   git commit -m "feat(p$ARGUMENTS): <phase name>"
   ```

4. Review: `code-reviewer` and `security-reviewer` (+ `ux-reviewer` if the phase has UI) in parallel.
   Fix all Blocker/Critical/High findings (add a regression test for each bug).
   ```
   git add -A
   git commit -m "fix(p$ARGUMENTS): address review findings"
   ```

5. Verify: brief `verifier` with ONLY: "Verify phase P$ARGUMENTS per docs/build/PHASES.md." Do not pass
   your summaries or expectations.

6. Fix loop: for every FAIL — reproduce, add/adjust a regression test (never weaken), fix, re-run, then
   ```
   git add -A
   git commit -m "fix(p$ARGUMENTS): <what was fixed>"
   ```
   and re-run the verifier. After 3 failed loops STOP and ask the human.

7. Human gate — present: what was built (bullets), gate table with evidence, test/coverage numbers from
   real output, SPEC-GAPs and the conservative choices taken, open risks, next phase preview.
   WAIT for the human to say "approved".

8. Close after approval:
   - Update `docs/build/STATUS.md`, `docs/CHANGELOG.md`, `docs/build/OPEN_QUESTIONS.md`.
   ```
   git add -A
   git commit -m "docs(p$ARGUMENTS): phase report and status"
   git tag p$ARGUMENTS-verified
   ```
   Then stop. Do not start the next phase.

Git: plain commands only, one-line messages, no co-author lines or trailers, never push.
