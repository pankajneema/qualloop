---
description: Re-run independent verification of a phase in a fresh subagent context. Usage - /verify-phase 3
argument-hint: <phase number>
---

Delegate to the `verifier` subagent with exactly this brief and nothing else:

"Verify phase P$ARGUMENTS per docs/build/PHASES.md and CLAUDE.md. Write docs/build/phases/P$ARGUMENTS-verification.md."

When it returns, show the human the verdict, the gate table and any failures with reproduction steps.
Do not fix anything in this command.
