# ADR-001 — Modular monolith with enforced module boundaries

- Status: Accepted (2026-10-03)
- Spec: §5.3 (no microservices/Kafka/Kubernetes), §22, §22.1, §24.1

## Context
The blueprint mandates "Modular monolith + background workers" (§22) with the module list in §22.1, built by a
2-person team in 12–16 weeks, while the data model must allow Part B without rewrites. Module coupling is the main
long-term risk: NCR, SCAR, effectiveness, finance and metrics all reference each other.

## Options considered
| Option | Pros | Cons |
| --- | --- | --- |
| A. Single package, no enforced boundaries | fastest start | cycles and cross-module ORM access within weeks; hard to extract later |
| B. Modular monolith, boundaries enforced by `import-linter`, public `service.py` per module, in-transaction hook bus + outbox for inverse reactions | one deploy, one DB transaction for invariants, explicit seams | discipline + CI contract maintenance |
| C. Microservices | independent scaling | forbidden by §5.3; distributed transactions break money/quantity invariants |

## Decision
Option B. Modules exactly as §22.1 under `api/app/`. Rules (ARCHITECTURE.md §3.1):
1. Cross-module imports only via `<module>.service`, `.events`, `.schemas`.
2. Fixed dependency order (layers contract); inverse same-transaction reactions via `core.hooks`; async reactions via outbox events.
3. Each module owns its tables (DATA_MODEL.md); other modules read them through the owner's service or SQL views it publishes.
4. Placement decisions where §22.1 is silent: defect codes/events/attributions → `receipts` (rejected quantity vs receipt
   denominator); decision gate → `scar` (§22.1 comment "decision gate"); `ai_extractions` → `documents`
   (`ai` stays a stateless capability); `messages`, `contact_consents`, `tasks` → `notifications`; My Work, Supplier 360,
   case payload → `reports`. Supplier-facing routes live with the data they serve (M4): `/supplier/scar/*` → `scar`,
   `/supplier/requirements` and `/supplier/documents/*` → `documents`. `supplier_access` keeps only link exchange, OTP,
   session and `require_supplier_session(purpose)`. SCAR close after effectiveness is driven by `effectiveness`
   calling `scar.service` (no `POST /scars/{id}/close`).
5. One container image, several entrypoints (api, worker, dispatcher, scheduler).

## Consequences
- Invariants spanning modules (e.g. scar → ncr state) run in one ACID transaction.
- `import-linter` contracts are part of `make lint`; a violation fails CI.
- Extraction of a module later is possible because its public surface is already explicit.

## Revisit when
- A single module's load needs independent scaling that worker-queue separation (SCALING.md S-04) cannot provide, or
- more than ~4 teams work on the codebase concurrently with recurring merge conflicts across modules.
