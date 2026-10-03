# P02 — Masters & imports — Plan

- Date: 2026-10-03
- Phase source: `docs/build/PHASES.md` §P02
- Blueprint: §6.2, §6.7, §7.5, §8 C2, §8 C3, §15.6, §17.3 (consent records), §21.1–§21.2 (export permission, formula injection), §23 (onboarding import)
- Contracts:
  - DATA_MODEL.md §2 (7 masters tables), §7 (`import_batches`, `import_records`), §0.7 list-sort indexes
  - API.md §3.2 (masters commands, P02 subset), §3.3 (imports), §5 (masters and imports queries), §6 (rate limits)
  - ARCHITECTURE.md §6.1 (`imports` queue), §7 (events), §8.3 (upload and import flow)
  - INVARIANTS.md: INV-PLT-08, INV-MST-01..05, INV-IMP-01, 02, 04, 05, 06, 08, INV-SEC-03 (export part), INV-SEC-05
- ADRs: 003, 004, 006, 008, 011, 013, 014; DESIGN_SPEC.md
- Open gaps applied: A-06, A-41, A-42, A-70, A-75, A-78, A-90, A-93; new ones in §8

## 1. Goal

A customer's suppliers, contacts, parts and mappings can be loaded from messy Excel safely, and maintained in the web app.
This is the first phase with screens.

## 2. Scope

### 2.1 Tables (migration `0003_masters_imports`)

| Table | Source | Notes |
| --- | --- | --- |
| `suppliers` | §6.2, DM §2.1 | `status*` written only by `change-status` (INV-MST-03); `archived_at`; GSTIN not unique |
| `supplier_contacts` | DM §2.2 | lifecycle CHECKs; `replaced_by_contact_id`; SS policies as DM §0.5 (supplier sees own contact row; no supplier actor until P05); `contacts_sysfn` policy is P05 (STOP resolution), not created now |
| `contact_consents` | DM §2.3 | CR+u(status, revoked_at, updated_*); re-opt-in inserts a new row |
| `customers`, `parts`, `customer_parts`, `supplier_parts` | DM §2.4–2.7 | archive, never delete; `parts` SS policy as DM §0.5 |
| `import_batches`, `import_records` | DM §7 | `import_records` CR (append-only); written at confirm time |

Column-level UPDATE grants follow the P01 pattern (only the mutable columns). List-sort indexes come from DM §0.7.
The supplier-scoped RLS predicates for `parts` and `supplier_contacts` reference P04/P05 tables (ncrs, ncr_scar_links). Each table keeps `p_supplier_deny` until the tables in its predicate exist; the scoped policy lands in that later phase. The `test_every_rls_table_has_supplier_policy` expected list is updated per phase.

### 2.2 Commands (API.md §3.2, §3.3, plus verbatim §24.2 items 9, 10, 11)

| Endpoint | Perm | Reason | Idem. | Event |
| --- | --- | --- | --- | --- |
| `POST /suppliers` · `/suppliers/{id}/update` · `/suppliers/{id}/archive` | Q | archive: yes | opt | `SUPPLIER_CREATED`/`_UPDATED`/`_ARCHIVED` (derived) |
| `POST /suppliers/{id}/change-status` | Q+CA | yes | opt | `SUPPLIER_STATUS_CHANGED` (§22.3) |
| `POST /suppliers/{id}/contacts` · `/contacts/{id}/update` · `/contacts/{id}/set-quality-contact` | Q | — | opt | derived |
| `POST /contacts/{id}/verify/start` · `/contacts/{id}/verify/confirm` | Q | — | opt | `CONTACT_VERIFIED` (derived) |
| `POST /contacts/{id}/disable` | Q | yes | opt | `CONTACT_DISABLED` + revocation hook |
| `POST /contacts/{id}/replace` | Q | yes | opt | `CONTACT_REPLACED` + revocation hook (SCAR reassignment hook point, P05) |
| `POST /contacts/{id}/consents` | Q | — | opt | derived |
| `POST /customers` · `/customers/{id}/update` · `/customers/{id}/archive` | Q | archive: yes | opt | derived |
| `POST /parts` · `/parts/{id}/update` · `/parts/{id}/archive` | Q | archive: yes | opt | derived |
| `POST /customer-parts` · `/customer-parts/{id}/archive` | Q | — | opt | derived |
| `POST /supplier-parts` · `/supplier-parts/{id}/update` · `/supplier-parts/{id}/archive` | Q | — | opt | derived |
| `POST /imports` | Q | — | opt | — (response carries `file_hash_seen_before` + previous batch ids) |
| `POST /imports/{batch}/map` · `/validate` · `/cancel` | Q | — | opt | — |
| `POST /imports/{batch}/confirm` (verbatim §24.2 #24) | Q | — | **required** | `IMPORT_CONFIRMED` |

Not in P02, although API.md §3.2 lists them:
- `defect-codes` (§6.3, P04) and `document-requirements` (§6.4, P03): their tables belong to those phases.
- `contacts/{id}/anonymise` (INV-SEC-07, P05).
- Generic `/exports/{list}.xlsx` (§16 C14, P08).

### 2.3 Queries (API.md §5)

`/suppliers` (`q`, `status`, `category`, `archived`; sorts `name`, `code`, `updated_at`; keyset), `/suppliers/{id}`,
`/suppliers/{id}/contacts`, `/contacts/{id}` (incl. consents, computed `needs_reverification`), `/customers`, `/parts`,
`/parts/{id}`, `/supplier-parts`, `/customer-parts`, `/imports`, `/imports/{batch}`, `/imports/{batch}/preview`,
`/imports/{batch}/records`, `/imports/{batch}/report.xlsx` (Q only; V denied A-70; logged to `activity_log`; formula-neutralised).

### 2.4 Import engine (§8 C3, ARCHITECTURE §8.3)

```text
upload-url (purpose import, xlsx/csv ≤ 20 MB) → PUT → POST /imports {entity, key, file_name}
  → file scan job (P01 files.scan) → batch 'uploaded'; file-hash match flagged in response and on the batch
→ detect columns (header row 1, first sheet) → POST /map (prefilled from the tenant's last mapping for that entity) → 'mapped'
→ POST /validate → imports-queue job: parse, normalise, row hash, natural key, classify each row
     valid | duplicate (natural key exists, same values, or repeated in file) | review (natural key exists, changed values, A-41)
     | rejected (validation error) | unmapped (reference not found, e.g. supplier code in supplier_parts)
  → preview JSON in object storage; counts on the batch → 'validated'
→ POST /confirm {accept_partial: bool}: if any non-valid rows and accept_partial ≠ true → 422 (INV-IMP-06)
  → import job: inserts valid rows in chunks; writes every import_record with final status and reason → 'completed'
  → report.xlsx generated (received/valid/imported/duplicate/rejected/unmapped/review + reason per row)
```

- Entities in P02: `suppliers`, `parts` and `supplier_parts` (A-112).
- Natural keys:
  - suppliers: GSTIN, else lower(name) + lower(city);
  - parts: `part_no`;
  - supplier_parts: supplier code + part_no (A-109).
- Duplicates are **reported, never merged or updated**.
- Imported suppliers get status `approved` and status_reason "initial import" (A-06, logged).
- Re-validation at confirm time catches rows that became duplicates after the preview.
- Performance budget: 5,000 rows from validate to completed in < 60 s locally (gate).

### 2.5 Contact lifecycle (§8 C2)

- **Verify (OTP, A-78):** 6 digits, 10 min TTL, 5 attempts, 3 sends/hour per contact. The OTP goes to the email or mobile on file through a channel adapter; email uses the real SMTP path. Mobile delivery uses the dev fake channel until P05 brings WhatsApp/SMS (A-110). A successful verify sets `verified_mobile_at` / `verified_email_at`.
- **Re-verification:** computed `needs_reverification` = active and (mobile unverified or `verified_mobile_at` older than 180 days). It is shown in the UI. Enforcement at link issuance comes in P05 (A-111).
- **Disable** requires a reason and calls the in-transaction hook `contact.revoke_access(contact_id)`. In P02 the hook has no subscribers except a test subscriber; P05 subscribes link and session revocation.
- **Replace** creates the new contact and disables the old one with `replaced_by_contact_id`, calling the same hook plus `contact.replaced(old, new)` (SCAR reassignment point, P05). The old contact and its history are kept.

### 2.6 Screens (DESIGN_SPEC, ADR-013; en + hi)

- Login and password reset (A-93).
- App shell: dark left nav 232 px, header with title and one primary action, bottom bar below 640 px.
- **Suppliers list:**
  - search `q`, filters for status and category, an archived toggle;
  - keyset "Load more";
  - the supplier status chip is outlined (never risk-styled, UX rule 6).
- **Supplier create/edit:**
  - status is required on create (A-06);
  - status changes go only through a ReasonDialog, enabled only for `can_approve` users.
- **Contacts** (on the supplier page):
  - add and edit, verify by OTP, set quality contact;
  - disable (ReasonDialog) and replace (ReasonDialog);
  - consent per channel;
  - re-verification badge.
- **Parts:** list, create and edit, link to suppliers (supplier_parts with ppm_target) and to customers.
- **Import wizard:**
  - steps: upload → map columns → validate (progress) → preview with tabs for errors, duplicates, unmapped and review → confirm (explicit partial-confirm checkbox) → result with counts and a report.xlsx download;
  - the file-hash warning is shown at upload.

Copy follows DESIGN_SPEC rules: errors say what happened, what we did and what to do, and buttons are verbs.

## 3. Invariants proven in P02

INV-PLT-08, INV-MST-01, 02, 03, 04 (hook part), 05 (reason + hook part), INV-IMP-01, 02 (suppliers, parts), 04, 05, 06, 08,
INV-SEC-03 (Viewer cannot export the import report), INV-SEC-05, INV-PLT-01 (new tables in the RLS parametrised tests), INV-PLT-10 (new commands in the viewer test).

## 4. Edge cases

- Same file twice: flagged at upload, before processing. A second confirm imports 0 rows and reports all rows as duplicates.
- Duplicates inside one file (two rows with the same GSTIN): the first is valid and the later ones are `duplicate` with the row number of the first.
- Supplier without GSTIN: name + city key, normalised (trim, collapse spaces, case-fold). Without both GSTIN and city: rejected (A-109).
- Same natural key with changed values goes to `review` (A-41). Never updated.
- `supplier_parts` row whose supplier code or part_no doesn't exist goes to `unmapped`, with a reason naming the missing reference.
- Excel: empty rows are skipped, not counted. Merged headers, leading/trailing spaces, numeric GSTIN or part_no read as float (e.g. `1234.0`), dates are ignored for masters, and `=`-prefixed cells in input are stored as text.
- CSV encodings: UTF-8 with or without BOM; others are rejected with a message.
- Formula injection: report cells starting with `= + - @ \t \r` are prefixed with `'`.
- Archived masters are excluded from pickers and import matching. Rows matching an archived supplier go to `review`.
- Status change without a reason → 422. Without `can_approve` → 403. Same status → 409 `invalid_transition`.
- Supplier `update` never touches the status columns, even if they are sent: 422 (`extra=forbid`).
- Contact replace on an already-disabled contact → 409. Replacing a contact with itself → 422.
- Concurrent confirm of the same batch: one wins and the other gets 409.
- Cancel after confirm: 409.

## 5. Test list (qa-engineer writes first)

**DB/RLS:** P01 parametrised tests extended to the 9 new tables; `test_part_can_link_to_many_customers`; supplier status CHECK values; contact lifecycle CHECKs; `import_records` append-only; column grants.

**Masters commands:**
- `test_change_status_without_reason_rejected`, `test_change_status_without_can_approve_rejected`, `test_change_status_logs_before_after`
- `test_supplier_update_command_ignores_status_fields`
- `test_supplier_archive_sets_archived_at_and_keeps_references`, archived part excluded from the picker query
- `test_disable_contact_requires_reason`, disable calls the revocation hook
- replace calls the hook, keeps the old contact and its history, and links via `replaced_by_contact_id`
- contact OTP verify happy path, wrong code, expiry, attempts, and send rate limit
- consent opt-in, opt-out and re-opt-in history
- `needs_reverification` at the 179/180/181-day boundaries
- viewer denied on every new command (parametrised)

**Imports:**
- `test_same_file_hash_flagged_before_processing`
- 5,000-row supplier file imported twice → 0 new suppliers, report shows 5,000 duplicates, and < 60 s (timed)
- `test_duplicate_supplier_by_gstin_reported_not_merged`, `test_duplicate_supplier_by_name_and_city_reported_not_merged`, `test_duplicate_part_by_part_no_reported`
- `test_changed_row_with_same_natural_key_goes_to_review_not_update`
- `test_partial_import_requires_explicit_confirmation`
- `test_import_report_counts_reconcile_to_rows_received`, `test_import_report_has_reason_per_non_imported_row`
- `test_export_neutralises_formula_injection`, `test_viewer_cannot_export_excel` (import report), `test_export_writes_activity_log`
- unmapped supplier_parts; confirm-time revalidation; concurrent confirm → 409; tenant isolation of batches and previews

**Web:**
- vitest for components: StatusChip outlined, ReasonDialog requires a reason, Indian number formatting
- en/hi key parity
- Playwright E2E:
  - login;
  - import wizard happy path (upload → map → validate → confirm → report download);
  - import wizard error path (errors and duplicates shown; partial confirm blocked until the box is checked);
  - suppliers list search and filter;
  - phone 360 px project for login and the suppliers list.

## 6. Who does what

| Step | Agent | Files |
| --- | --- | --- |
| Tests first (api + web unit + Playwright E2E + UI selector contract) | qa-engineer | `api/tests/**`, `web/src/**/*.test.ts(x)`, `web/e2e/**`, `docs/build/phases/P02-test-contract.md` |
| Migration, masters + imports modules, jobs, report.xlsx | backend-engineer | `api/**` |
| Screens, API client, i18n | frontend-engineer (parallel with backend) | `web/**` except tests |
| Review | code-reviewer, security-reviewer, ux-reviewer (parallel) | read-only |
| Verify | verifier | read-only |

data-engineer: not needed; there are no metrics or money in P02. devops: only if E2E in CI needs stack changes.

## 7. New dependencies (to confirm at build; none needs its own server)

- `openpyxl`: read and write xlsx (ADR-014 Excel generation).
- Python `csv` (stdlib).
- Web: an OpenAPI type generator (`openapi-typescript`, dev-only), as API.md §1.7 requires. No UI component library: components are built from tokens.

## 8. SPEC-GAPs raised by this plan (none changes PHASES scope)

| ID | Question | Conservative default |
| --- | --- | --- |
| A-109 | Natural key for `supplier_parts` (§8 C3 lists suppliers, parts, receipts only). And a supplier row with neither GSTIN nor city? | supplier code + part_no. A supplier row with neither GSTIN nor city is rejected ("needs GSTIN or city to detect duplicates") |
| A-110 | "Verify mobile by OTP" (§8 C2): how is the OTP delivered before WhatsApp/SMS exist (P05)? | Channel adapter: email is real now; mobile uses the dev fake channel (A-91). Real mobile delivery is wired in P05. Production mobile verification is not usable until P05 |
| A-111 | Where is the 180-day re-verification enforced? | Computed `needs_reverification` shown in P02; enforced at magic-link issuance in P05 |
| A-112 | Which import entities in P02? (§6.7 lists six) | suppliers, parts, supplier_parts. receipts/ncrs come in P04, certificates_meta in P03. The 5,000-row mandatory test uses the supplier entity; the receipt variant of INV-IMP-03 is P04 |
| A-113 | "Map (saved per tenant)": no table for saved mappings | Prefill from the tenant's most recent batch mapping for the same entity; no new table |
| A-114 | Accepted file formats and layout | `.xlsx` (first sheet) and `.csv` (UTF-8, with or without BOM); header in row 1; ≤ 20 MB (A-97) |
| A-115 | API.md §3.2 lists defect-codes, document-requirements and contact anonymise among the masters | Built in their own phases (P04, P03, P05), not P02 |

## 9. Risks

- 5,000 rows in < 60 s: rows are validated against existing keys with set-based queries and inserted in chunks, never row by row. The test is timed in CI.
- E2E tests are written before the UI exists. qa fixes the routes, accessible names and labels in a UI contract, and the frontend builds to it.
- Backend and frontend run in parallel against API.md. Contract drift is caught at integration by the generated OpenAPI types and E2E.
- The ClamAV scan of xlsx (zip) files can be slow on large files. The scan time is part of the 60 s budget only after upload; the budget is measured from validate.
