# ADR-005 — IDs, money and time

- Status: Accepted (2026-10-03)
- Spec: §6 (uuid ids, numbering), §6.3 `amount_inr`, §7.3 (plant timezone), §9 C6 (calendar hours), §12, §14.5; CLAUDE.md §6

## Context
CLAUDE.md requires UUIDv7 ids, money as BIGINT paise, `timestamptz` UTC, business dates in plant timezone. PostgreSQL 16
has no native UUIDv7 function; Python 3.12 has no `uuid.uuid7`. The spec names money columns `amount_inr`.

## Decisions

### 1. IDs
| Item | Decision |
| --- | --- |
| Generation | Application, `uuid6.uuid7()` in `core/ids.py`; SQLAlchemy `default=new_id` |
| SQL fallback | `app_uuid_v7()` PL/pgSQL (timestamp ms + random) for SQL-side inserts (seeds, triggers) |
| Exposure | UUIDs in API paths; human numbers (`ncr_no`, `scar_no`, `dn_no`) for display/search |
| Ordering | UUIDv7 is time-ordered → keyset tie-breaker and good B-tree locality |

### 2. Money
| Item | Decision |
| --- | --- |
| Type | `bigint` paise; `CHECK (> 0)` on all amounts |
| Naming | `amount_paise` (spec `amount_inr`, SPEC-GAP A-01 — avoids 100× unit errors) |
| Python | `int` only; `core/money.py` has `Paise = NewType('Paise', int)`; floats rejected by Pydantic (`StrictInt`) |
| Pro-rata | integer arithmetic: `floor(R × outstanding_i / Σ outstanding)`, remainder (paise) to largest outstanding, tie → lowest id (A-39) |
| Display | web formats ₹ with Indian grouping (`₹4,20,000`), from paise |
| AI provider cost | `cost_usd_micros` bigint — operational cost, not business money (A-77) |

### 3. Time
| Item | Decision |
| --- | --- |
| Instants | `timestamptz`, UTC in DB and API (RFC 3339 with offset) |
| Business dates | `date` columns (`grn_date`, `incurred_on`, `recovered_on`, `dn_date`, `issue_date`, `expiry_date`, `written_off_on`, `valid_until`) interpreted in plant timezone |
| Plant "today" | `plant_today(plant) = (now() AT TIME ZONE plants.timezone)::date` |
| Supplier-level "today" (certificates, requirements, exceptions — no plant) | latest local date among the tenant's plants (conservative: expiry is reached as soon as it is reached in any plant) — SPEC-GAP A-08 |
| SLA due | `issued_at + interval 'N hours'` calendar hours (§9 C6); plant holiday calendar is R1.1 |
| Periods | calendar month in the plant timezone (A-52): `period_start` = 1st, `period_end` = last day; `cutoff` = `(period_end + 1)` 00:00 plant local → UTC instant; event belongs to period iff `start_utc ≤ ts < cutoff` |
| Dates in UI | "3 Oct 2026", plant timezone (DESIGN_SPEC) |
| Tests | `time-machine` freezes time; fixtures set plant timezone explicitly |

### 4. Numbering
`NCR-{plant}-{YYMM}-{seq}`, `SCAR-{YYMM}-{seq}`, `DN-{YYMM}-{seq}`; `seq` ≥ 3 digits; allocation by transaction-scoped
advisory lock, then `max(split_part(no, '-', k)::int) + 1` (k = 4 for NCR, 3 for SCAR/DN), with the unique constraint as backstop (DATA_MODEL.md §10, A-71). No counter table.

## Consequences
- No float anywhere in money paths; mypy + Pydantic strict types catch it.
- Period logic lives in one module (`core/timeutils.py`) used by metrics, snapshots, numbering and SLAs.

## Revisit when
- PostgreSQL 18+ is available on the managed service (native `uuidv7()`), or
- a tenant needs non-INR currency (Part B; would add a currency column — new ADR).

## Human decision (2026-10-03)

`amount_paise` (BIGINT) approved (A-01). UI and exports show rupees with Indian grouping.
