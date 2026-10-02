# QualLoop — Claude Code Build Kit

A ready-to-use setup that makes Claude Code build QualLoop phase by phase like a senior engineering team:
architecture first, tests first, independent verification in fresh contexts, human approval at every gate,
and clean plain-git commits.

## What's inside

```
CLAUDE.md                         Project constitution: sources of truth, team, phase protocol, git rules, human gates
.claude/settings.json             No co-author trailers; blocks push/remote/rebase/reset/amend; hides .env
.claude/agents/                   10 specialist subagents (each runs in its own fresh context)
  architect.md                    Architecture, ADRs, data model, scaling path (Opus)
  qa-engineer.md                  Writes failing tests from the SPEC before code exists
  backend-engineer.md             FastAPI, migrations + RLS, commands, outbox, workers
  data-engineer.md                Metrics, money invariants, attribution, snapshots (Opus)
  frontend-engineer.md            Next.js screens to DESIGN_SPEC, i18n, PWA
  devops-engineer.md              Docker, CI/CD, IaC, observability, backups
  security-reviewer.md            Tenant isolation, supplier access, OWASP (read-only, Opus)
  code-reviewer.md                Correctness, boundaries, transactions, N+1 (read-only, Opus)
  ux-reviewer.md                  Design + UX rules + accessibility (read-only)
  verifier.md                     Independent phase gate check, evidence only (read-only, Opus)
.claude/commands/
  architecture.md                 /architecture       → Phase 0
  build-phase.md                  /build-phase <N>    → one full phase with gates and commits
  verify-phase.md                 /verify-phase <N>   → fresh independent verification
  fix-bug.md                      /fix-bug <desc>     → test-first bug fix + commit
  status.md                       /status             → where we are, what's next
docs/build/PHASES.md              P00–P10 + scale track: scope, mandatory tests, gates
docs/build/STATUS.md              Phase tracker
docs/build/OPEN_QUESTIONS.md      SPEC-GAP register
docs/design/DESIGN_SPEC.md        Typography, colours, components, screens, 10 UX rules
docs/blueprint/                   Put Supplier_Quality_OS_Blueprint_FINAL.md here
docs/CHANGELOG.md
```

## Setup (once)

```bash
mkdir qualloop && cd qualloop
git init
# copy everything from this kit into the folder (including the hidden .claude folder)
# copy the frozen blueprint:
cp /path/to/Supplier_Quality_OS_Blueprint_FINAL.md docs/blueprint/
git add -A
git commit -m "chore: project kit and frozen blueprint"
claude
```

## Run

| Step | Type in Claude Code | You do |
| --- | --- | --- |
| 1 | `/architecture` | Read the summary, ADRs and ambiguity list. Reply "approved" or give changes. |
| 2 | `/build-phase 1` | Review the gate report. Reply "approved". |
| 3 | `/build-phase 2` … `/build-phase 9` | Same, one phase per session (start a new session with `/clear` between phases). |
| 4 | Pilot plant goes live | — |
| 5 | `/build-phase 10` | R1.1 items |
| any time | `/status`, `/verify-phase N`, `/fix-bug <description>` | — |

Tips:
- Use a fresh session (`/clear`) for each phase; everything important lives in files, not chat memory.
- Answer SPEC-GAP questions at each gate; decisions go into `docs/build/OPEN_QUESTIONS.md`.
- Commits are local only. Push yourself when you choose (`git push` is blocked for the agent).
- If your Claude Code version uses a different setting name for co-author attribution, CLAUDE.md §4 still
  forbids trailers; check `git log` after the first commit.

## What this kit cannot guarantee

No prompt makes software bug-free. This kit makes errors unlikely to survive: tests are written from the spec
by an agent that never saw the code, every phase is verified by a fresh agent that must show command output,
money and tenant rules are enforced in the database, and you approve every phase before the next starts.
