---
description: Fix a reported bug test-first and commit it. Usage - /fix-bug <description>
argument-hint: <bug description>
---

Bug: $ARGUMENTS

1. Reproduce: find the spec rule (§) the bug violates; write a failing regression test (or ask
   `qa-engineer` to, from the spec). Show it failing.
2. Fix with the right subagent (backend / data / frontend). Run the full suite, lint, types.
3. Ask `verifier` to re-verify only the gate items of the affected phase.
4. Commit:
   ```
   git add -A
   git commit -m "fix(pNN): <short description>"
   ```
   (pNN = the phase that owns the affected module.) No co-author lines or trailers. Never push.
5. Report root cause, fix, test name, and whether any other module could have the same bug.
