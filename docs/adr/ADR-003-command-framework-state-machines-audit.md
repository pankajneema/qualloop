# ADR-003 — Command framework, state machines and audit log

- Status: Accepted (2026-10-03)
- Spec: §4.11, §7, §7.5, §22.2, §24.1.2, §24.2

## Context
"All transitions go through command endpoints, are authorised, write activity_log, and emit an outbox event. No generic
update status endpoint" (§7). Records are never silently changed (§4.11). Debit note creation must be idempotent (§22.2).

## Options considered
| Option | Pros | Cons |
| --- | --- | --- |
| A. Hand-written endpoint code per transition | flexible | inconsistent audit/outbox; easy to forget a step |
| B. DB triggers write the audit log | cannot be bypassed | no reason/session/IP/actor semantics without GUC plumbing; before/after of aggregates not row-level |
| C. **Command base class + declarative state tables; app writes audit + outbox; DB triggers guard invariants** | one pipeline, testable, explicit | some framework code in `core` |
| D. Event sourcing | full history | far beyond R1 needs; metrics and RLS harder |

## Decision
Option C.
- `core.commands.Command[In, Out]` with `name`, `permission` (role set, `requires_can_approve`, plant-scope extractor),
  `requires_reason`, `idempotency` (required/optional), `handle(ctx, input)`.
- `run_command` pipeline, one transaction: idempotency reservation → authorise → load & `SELECT … FOR UPDATE` →
  validate (Pydantic + state-machine guard) → mutate → `activity_log` (before/after JSON of the aggregate's public
  read-model, reason, actor_type, actor_id, session_id, ip) → `outbox_events` → in-transaction hooks → store
  idempotent response → commit.
- State machines (NCR, SCAR, certificate, requirement, effectiveness, debit note status) are transition tables in each
  module's `state_machine.py`; the guard rejects unknown pairs with `409 invalid_transition`.
- Actor types (the same values in `app.actor_type` and `activity_log.actor_type`): `user`, `supplier_session`, `system` (workers/scheduler), `ai` (never allowed to call state-changing
  commands — every command's permission excludes `ai`; INV-AI-02).
- Idempotency keys: Postgres table `idempotency_keys` (proposed, A-73) so the replay record commits atomically with the
  business change. Redis is not used for this because a Redis write cannot be atomic with the DB commit.
- **Isolation and locking (M1).**
  - Every command transaction runs at **READ COMMITTED**, the Postgres default, which is set explicitly on the engine.
  - Commands and DB triggers take row locks **first**, with `SELECT … FOR UPDATE`, and only then compute sums in a **separate statement**. Each statement gets a fresh snapshot, so the sum sees rows committed by any transaction that held the lock.
  - Lock order is fixed for every money command and trigger: `debit_notes` row → its `debit_note_allocations` ordered by `id` → `ncr_costs` ordered by `id`. Other aggregates lock the aggregate root first (SCAR before NCRs, by `id`). This prevents deadlocks.
  - Deadlock or serialization errors map to `409 conflict`. Commands are retried by the client, never silently by the server.
- `activity_log` is append-only (grants + trigger). Export/download queries also write an `activity_log` row (§16 C14).

## Consequences
- Every new command needs: transition entry, permission, test for allowed + forbidden + viewer-denied + audit/outbox.
- Before/after is the read-model, so PII in logs follows the read-model's masking (ADR-019).
- The audit table grows fastest (SCALING.md S-05).

## Revisit when
- `activity_log` write adds > 20 ms p95 to commands, or
- auditors require tamper-evidence beyond DB grants (then: hash-chain column or WORM export — new ADR).
