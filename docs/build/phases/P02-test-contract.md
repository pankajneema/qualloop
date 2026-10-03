# P02 test contract

The P02 tests were written from `docs/build/PHASES.md` P02, `P02-plan.md`, the blueprint sections named there and
`docs/architecture/` (API.md, DATA_MODEL.md, INVARIANTS.md). Where those documents do not name a Python symbol, an HTTP
body, a log field or a UI label exactly, the tests assume the choices below. The implementers build to this list. If an
entry is wrong for a good reason, say so and ask the orchestrator; do not change the test silently.

The P01 contract (`P01-test-contract.md`) still holds. Everything marked **doc** comes from a named document. Everything
else is an assumption made by the tests (**assumed**). Section 6 lists the places where the documents conflict or are
silent and what each test assumes.

Python tests import P02 symbols late through `tests/factories/contract.py::load`, so a missing module fails only the
tests that need it. Web unit tests do the same through `web/src/test/load.ts` (always an `@/...` alias path).

## 1. Python interfaces

| Module | Symbol | Contract |
| --- | --- | --- |
| `app.core.excel` | `neutralise_cell(value: object) -> object` | `str` starting with `=`, `+`, `-`, `@`, TAB or CR gets a leading `'`; every other value (other strings, numbers incl. negative, bool, `None`) is returned unchanged with the same type; idempotent (a neutralised cell starts with `'`). Used by the import report now and by exports in P08. **doc** ADR-014, INV-IMP-08 (module and function name assumed) |
| `app.imports.normalise` | `clean_cell(value) -> str \| None` | `None`, `""`, whitespace-only -> `None`; `str` -> stripped, otherwise unchanged (a text `"1234.0"` stays text; `=SUM(1,2)` stays); `int` -> `str`; integral `float` -> integer text (`1234.0` -> `"1234"`, `123456789012345.0` -> `"123456789012345"`); non-integral float -> `"12.5"`. **doc** P02 plan 4 (names assumed) |
| `app.imports.normalise` | `normalise_text(s: str) -> str` | trim, collapse inner whitespace runs to one space, `casefold()` (`"Straße"` -> `"strasse"`). **doc** P02 plan 4 |
| `app.imports.normalise` | `supplier_natural_key(gstin, name, city) -> str \| None` | GSTIN present: key from the GSTIN only (trimmed, upper-cased); otherwise name + city normalised with `normalise_text`; `None` when there is no GSTIN and name or city is missing/blank (A-109). A GSTIN key never equals a name+city key. Return value is opaque, tests compare keys only. **doc** blueprint 8 C3, A-109 |
| `app.imports.normalise` | `row_hash(values: Mapping[str, object]) -> str` | SHA-256, 64 lowercase hex, over the normalised values: independent of key order, of outer whitespace and of blank vs missing; changes with any value; fields are delimited (`("ab","c")` differs from `("a","bc")`). Case is not folded. **doc** DATA_MODEL 7.2 |
| `app.masters.channels` | `FAKE_SENT: list[dict[str, str]]` | the dev fake mobile channel (A-110, A-91). The worker appends `{"channel": "mobile", "to": <E.164>, "body": <text with exactly one 6-digit code>, "idempotency_key": <str>}`; tests clear it. Email uses the P01 SMTP path (mailpit). In `QL_ENV` `local` and `ci` only. **assumed** |
| `app.core.hooks` | names `contact.revoke_access`, `contact.replaced` | published with `hooks.publish(name, session, ...)`, inside the command transaction: `contact.revoke_access(session, contact_id)` once for the OLD contact on disable and on replace; `contact.replaced(session, old_id, new_id)` once on replace, after the new contact row exists. A hook that raises rolls the whole command back (P01 hook bus). **doc** P02 plan 2.5 (argument shapes assumed) |
| `app.worker` | actors `imports.validate`, `imports.run` | queue `imports`, kwargs `tenant_id` (str UUID) and `batch_id` (str UUID); registered when `app.worker` is imported; run under `tenant_tx(tenant_id, actor_type="system")`. `validate` parses, classifies, writes the preview JSON to object storage and moves `mapped -> validated`. `run` revalidates, inserts valid rows in chunks, writes every `import_records` row, builds the report and moves `importing -> completed` (or `failed`). A batch that is not visible under the message's tenant, or not in the expected status, makes the job a **no-op that returns normally** (no exception, no retry). Tests send with `send_with_options(kwargs=..., max_retries=0)`. **assumed** (queue `imports` is **doc** ARCHITECTURE 6.1) |
| `app.worker` | contact OTP send | the actor that delivers a verification code (email through `app.core.mail.send_email(..., idempotency_key=...)`, mobile through `app.masters.channels`). Registered in `app.worker`; any queue; tests run every declared queue in-process. **assumed** |
| `app.core.outbox.registry` | derived events | `SUPPLIER_CREATED`, `SUPPLIER_UPDATED`, `SUPPLIER_ARCHIVED`, `CONTACT_VERIFIED`, `CONTACT_DISABLED`, `CONTACT_REPLACED`, `IMPORT_CONFIRMED` are registered `derived=True` with an emitter; `SUPPLIER_STATUS_CHANGED` is `derived=False` with an emitter (so its P01 xfail becomes a real test). Every other P02 command emits one event whose name is registered (names free). **doc** ARCHITECTURE 7 |
| `app.core.commands.base` | `all_commands()` | contains the 28 P02 commands of section 2 with the permissions of API.md; path parameter names are free (`{id}`, `{batch}`, ...). Roles are `{"quality"}`; `change-status` has `requires_can_approve=True`. **doc** API.md 2, 3.2, 3.3 |
| tests | fixtures | `tests/conftest.py::drain` (in-process `imports` worker + `wait_idle`), `tests/factories/imports.py` (file builders and the `Importer` flow driver), `tests/factories/masters.py` (API creators), `tests/factories/rows.py::MASTERS_INSERTERS` (one minimal row per new table). Test-visible, do not change signatures. |

## 2. HTTP shapes

All paths are under `/api/v1`. Create and update commands answer `200` or `201` with the read model. Lists answer
`{"items": [...], "next_cursor": str | null}` (limit 1-200, default 50, bad cursor 400, cursor of another sort 400). All
commands accept an optional `Idempotency-Key` (UUID) except where marked **required**. **Unknown body fields are
rejected with 422** (`extra="forbid"`) on every P02 command, as the plan requires for `suppliers/{id}/update`.
Authorisation (401, 403) precedes validation and lookup. Foreign-tenant objects are 404, identical to missing ones.

### 2.1 Masters

| Endpoint | Body | Notes |
| --- | --- | --- |
| `POST /suppliers` | `{code, name, category, status, gstin?, city?, state?}` | `status` **required** (A-06). **A-116:** without `can_approve` (Quality or Admin) only `approved` is accepted; any other initial status is 403 `forbidden` with no row, no audit entry and no event; with `can_approve` all five are allowed. `category` in `raw_material, bought_out, job_work, service`. `gstin` matches `^[0-9A-Z]{15}$`. Duplicate `code` in the tenant -> 409 or 422 |
| `POST /suppliers/{id}/update` | any of `{code?, name?, gstin?, city?, state?, category?}` | never `status*` or `archived_at` (422, INV-MST-03). A `code` already in use -> 409 or 422 |
| `POST /suppliers/{id}/archive` | `{reason}` | sets `archived_at`; archiving an archived supplier -> 409 `invalid_transition` |
| `POST /suppliers/{id}/change-status` | `{status, reason}` | Q + can_approve (admin without the flag is 403). Same status -> 409 `invalid_transition`. `reason` 1-2000 after trimming |
| `GET /suppliers` | `?q&status&category&archived&sort&limit&cursor` | `q`: case-insensitive **contains** on name, code and GSTIN, `%` `_` `\` literal. `archived` default false; `true` includes archived suppliers. `sort` in `name` (default, case-insensitive asc), `code` (asc), `updated_at` (desc); anything else 400. Unknown `status`/`category`/`archived` values 400 or 422 |
| supplier read model | `id, code, name, gstin, city, state, category, status, status_reason, status_changed_by, status_changed_at, archived_at, created_at, updated_at` | `GET /suppliers/{id}` returns the same |
| `POST /suppliers/{id}/contacts` | `{name, role?, mobile?, email?}` | at least one of mobile (E.164) or email; cannot set verification, `active` or the quality flag |
| `POST /contacts/{id}/update` | any of `{name, role, mobile, email}` | changing `mobile` clears `verified_mobile_at`, changing `email` clears `verified_email_at`; `null` clears a value; leaving neither -> 422; lifecycle fields -> 422; disabled contact -> 409 or 422 |
| `POST /contacts/{id}/set-quality-contact` | `{}` | exactly one `is_quality_contact` per supplier; a disabled contact -> 409 or 422 |
| `POST /contacts/{id}/disable` | `{reason}` | -> `active=false`, `disabled_at`, `disabled_reason`; calls `contact.revoke_access`; disabled again -> 409 |
| `POST /contacts/{id}/replace` | `{reason, name, role?, mobile?, email?}` | answers the NEW contact; old one: `active=false`, `disabled_reason=reason`, `replaced_by_contact_id=new`; new one unverified, no consents, takes `is_quality_contact` from the old one; replaced/disabled old contact -> 409; any `replacement_contact_id` field -> 422 |
| `POST /contacts/{id}/verify/start` | `{channel: "mobile" \| "email"}` | 200/202/204; the code is sent by a worker, never in the response; destination missing -> 422; 4th send within an hour per contact -> 429 `rate_limited` + `Retry-After` <= 3600 |
| `POST /contacts/{id}/verify/confirm` | `{channel, code}` | `code` is a 6-digit string; success returns the contact (`verified_mobile_at` or `verified_email_at` set, only that channel). Wrong, expired, burnt and never-requested codes give the same 422 `validation_error` body. 5 attempts per code (the 5th may succeed, a 6th cannot). A newer code replaces the older |
| `POST /contacts/{id}/consents` | `{channel: whatsapp \| email \| sms, status: opted_in \| opted_out, source: otp_verification \| import \| manual \| stop_reply \| supplier_link}` | opt-out revokes the existing `opted_in` row (`status`, `revoked_at`); re-opt-in inserts a new row; a second opt-in while opted in -> 200/201/409/422 and never two `opted_in` rows |
| `GET /suppliers/{id}/contacts`, `GET /contacts/{id}` | | contact read model: `id, supplier_id, name, role, mobile, email, is_quality_contact, verified_mobile_at, verified_email_at, active, disabled_at, disabled_reason, replaced_by_contact_id, needs_reverification, consents:[{id, channel, status, source, consent_at, revoked_at}]`. The list includes disabled contacts. `needs_reverification` = active and (`verified_mobile_at` is null or older than 180 days); computed, never stored |
| `POST /customers`, `/customers/{id}/update`, `/customers/{id}/archive` | `{name, code}`, `{name?}`, `{reason}` | read model `{id, name, code, archived_at, ...}`; `code` unique per tenant |
| `POST /parts`, `/parts/{id}/update`, `/parts/{id}/archive` | `{part_no, name, category?, current_revision?}`, `{name?, category?, current_revision?}`, `{reason}` | no `customer_id` anywhere; `part_no` unique per tenant; `GET /parts` sort `part_no` only (else 400), default hides archived, `archived=true` includes them |
| `POST /customer-parts`, `/customer-parts/{id}/archive` | `{customer_id, part_id, customer_part_no?}`, `{}` | many-to-many; **A-119:** an active pair -> 409; a pair that exists archived is restored (same id, `archived_at` cleared, one `activity_log` row whose action ends in `restore`, no second DB row); archived or foreign customer/part -> 404/409/422 |
| `POST /supplier-parts`, `/supplier-parts/{id}/update`, `/supplier-parts/{id}/archive` | `{supplier_id, part_id, supplier_part_no?, ppm_target?}`, `{supplier_part_no?, ppm_target?}`, `{}` | Links are created `active` (A-117); `status` is not accepted by `create` or `/update` (422, INV-PLT-06). **A-119:** an active pair -> 409; an archived pair is restored like `customer-parts`. `ppm_target` is a strict positive integer <= 2147483647. `GET /supplier-parts?supplier_id&part_id` hides archived links and links to archived parts by default |
| `GET /customers`, `/parts`, `/supplier-parts`, `/customer-parts` | `archived`, filters | read-only for the Viewer too (Q,V) |

### 2.2 Imports

All `/imports*` endpoints are Q (Viewer 403, also for reads and the report). The `Idempotency-Key` on `confirm` is
**required** (missing -> 422 with `errors[].field == "Idempotency-Key"`).

| Endpoint | Request | Response / rules |
| --- | --- | --- |
| `POST /imports` | `{entity, key, file_name}` | `key` from `/files/upload-url` (purpose `import`) **already promoted by the scan job** (`scan_quarantined`); a key still in quarantine, quarantined, of another tenant (404), of another kind, or not a readable csv/xlsx -> 404/415/422 and **no batch**. `entity` in `suppliers, parts, supplier_parts` (`receipts`, `ncrs`, `certificates_meta` and unknown -> 422, A-112). `file_name` must end `.xlsx` or `.csv` (415/422 otherwise). CSV must be UTF-8 with or without BOM (A-114). Other encodings never become a batch: the P01 scan job already quarantines them as `content_type_mismatch` (checked against the stack), and if a future scanner lets one through, `POST /imports` answers 415/422 with `utf-8` in the message. Only the first sheet is read; header is row 1 |
| batch read model | | `id, entity, file_name, file_hash (sha256 hex of the bytes), status, mapping ({} until /map), suggested_mapping, columns (header texts in file order, no blanks), target_fields:[{name, required}], rows_received, rows_valid, rows_imported, rows_duplicate, rows_rejected, rows_unmapped, rows_review, started_by, confirmed_at, file_hash_seen_before, previous_batch_ids, created_at` |
| `POST /imports/{batch}/map` | `{mapping: {<target field>: <source column>}}` | `-> status "mapped"`. 422 when a target is unknown, a source column is not in `columns`, a value is blank/non-string, or a required target is missing. `suggested_mapping` of a new batch = the most recent saved mapping of the same entity in the tenant, restricted to entries whose source column exists in the new file (A-113). Required targets: suppliers `code, name, category` (optional `gstin, city, state`); parts `part_no, name` (optional `category, current_revision`); supplier_parts `supplier_code, part_no` (optional `supplier_part_no, ppm_target`) |
| `POST /imports/{batch}/validate` | `{}` | 200/202; enqueues `imports.validate`; afterwards `status "validated"` and the counts are set; writes **no** master rows and **no** `import_records` |
| `GET /imports/{batch}/preview` | `?status&limit&cursor` | before validate 404/409. items `{row_number, status: valid \| duplicate \| rejected \| unmapped \| review, reason, source_record_id, values}`, keyset by `row_number`, `status` filter (unknown value 400/422) |
| `POST /imports/{batch}/confirm` | `{accept_partial?: bool}` (strict bool) | `Idempotency-Key` required. Any non-valid row and `accept_partial` not `true` -> 422 `validation_error` or `invariant_violation` whose text contains `partial`; the batch stays `validated`. Otherwise `status "importing"`, enqueues `imports.run`, event `IMPORT_CONFIRMED`; activity_log `after.accept_partial` records the flag. Not `validated` -> 409 |
| `POST /imports/{batch}/cancel` | `{}` | allowed from `uploaded`, `mapped`, `validated`; otherwise 409 |
| `GET /imports/{batch}/records` | `?status&limit&cursor` | one item per received row, written at confirm time: `{row_number, status: imported \| duplicate \| rejected \| unmapped \| review, reason, target_id, source_record_id, row_hash}`; empty until confirm |
| `GET /imports/{batch}/report.xlsx` | | only for a `completed` batch (else 404/409); `Content-Type` xlsx, `Content-Disposition: attachment; filename=...xlsx`; writes `activity_log` (`object_type "import_batch"`, `action` containing `export`, actor, IP); 20 per hour per user then 429. Sheet `Summary`: column A label, column B integer, labels `Received, Valid, Imported, Duplicate, Rejected, Unmapped, Needs review`. Sheet `Rows`: header `Row, Status, Reason`, then one column per mapped target field (header = field name, value = normalised cell); one line per received row ordered by row number; `Status` uses the `import_records` tokens; every non-`imported` line has a reason. Every cell passes `neutralise_cell`; no formula cells |
| list | `GET /imports` | newest first (`created_at DESC, id DESC`), keyset |

Row semantics (A-41, A-109, P02 plan 4): `row_number` is the physical spreadsheet row (header = 1); empty rows are
skipped and not counted. Values are cleaned with `clean_cell`. A row is **valid** (new natural key), **duplicate**
(key exists with the same normalised values, or repeats an earlier row of the file; the reason names the first row as
`row N`), **review** (key exists with changed values; or the match is an archived supplier; or, **A-118**, the name + city of the row matches another non-archived supplier (or an earlier row of the file) under a different or missing GSTIN, or the row has no GSTIN and matches one that has one: the reason names both keys, i.e. contains `GSTIN`, `name`, `city`, and `row N` for an earlier row; never imported, never merged; the reason names the changed
fields and says `archived` for archived matches), **rejected** (reason names the field: `code`, `name`, `category`,
`gstin`, `ppm_target`, or both `gstin` and `city` for A-109; also a `code` already used by another supplier or repeated
for a different supplier in the file) or **unmapped** (supplier_parts only; the reason contains the missing supplier code
or part number). Duplicate reasons say `GSTIN` or `name` and `city`/`part`. Confirm revalidates against the current data:
rows that became duplicates or collide on `code` end as `duplicate`/`rejected`, and the batch still completes. Counters:
`received = valid + duplicate + rejected + unmapped + review` after validate;
`imported + duplicate + rejected + unmapped + review = received` after completion. Imported suppliers get
`status approved`, `status_reason "initial import"`, `status_changed_at` set and an activity_log row each (A-06).

### 2.3 Audit and events

`activity_log.object_type` is `supplier`, `contact`, `customer`, `part`, `customer_part`, `supplier_part` or
`import_batch`; `action` is `<object_type>.<verb>` (`supplier.change_status`, `contact.replace`, `import.confirm`, ...) with
the verb containing the command's verb (`update`, `archive`, `status`, `disable`, `replace`, `verify`, `map`, `validate`,
`cancel`, `confirm`, `create`). Creates have `before IS NULL`. `before` and `after` are the read model; contact rows hold
**masked** mobile (`+91******3210`) and no raw email (ADR-019); outbox payloads hold ids only. Each command writes one
activity_log row and one outbox event in the same transaction (equal `xmin`); `replace` may write up to three of each. The
import commands `create`, `map`, `validate`, `cancel` write an activity_log row (no event is required for them).
Query endpoints write nothing, except the report download.

## 3. Redis keys and settings

| Item | Contract |
| --- | --- |
| `otp:*` | the verification code is stored hashed under a key in the `otp:` family; TTL 1-600 s; neither the code nor the contact's mobile or email appears in a value or key. **doc** A-78, ADR-008 |
| `rl:*` | send limit 3 per hour per contact; export limit 20 per hour per user. **doc** API.md 6 |
| `idem:*`, `dramatiq:*` | as P01 |
| settings | none new. `QL_ENV` is `local` or `ci` in tests so the fake channel is allowed |

## 4. Database

Table and column names are those of DATA_MODEL 2 and 7. The tests rely on: CHECKs named in section 2 and 7 of that
document; composite foreign keys; `UNIQUE (tenant_id, code)` on `suppliers` and `customers`, `(tenant_id, part_no)` on
`parts`, the pair uniques on `customer_parts` and `supplier_parts`, `(tenant_id, batch_id, row_number)` on
`import_records`, the partial unique on opted-in consents; index definitions of DATA_MODEL 0.7 and 0.4
(`ix_suppliers_name` ... `ix_import_records_batch_row`, `supplier_contacts_mobile_idx`); policies `p_tenant` +
`p_supplier_deny` only on all nine tables; no DELETE; `import_records` has no UPDATE grant and the append-only trigger;
`contact_consents` UPDATE only on `status, revoked_at, updated_at, updated_by`; `import_batches` UPDATE excludes `id,
tenant_id, created_*, file_hash, entity, started_by`; `id, tenant_id, created_at, created_by` are never updatable on any
of the nine tables. Migration `0003*` sits directly on `0002` and `downgrade 0002` removes exactly the nine tables.
`import_batches.mapping` must be a JSON object; every counter is `>= 0`. **assumed** for the last three sentences.

## 5. UI contract (Next.js, ADR-013, DESIGN_SPEC)

Base URL `PLAYWRIGHT_BASE_URL` (default `http://localhost:3000`), same-origin `/api/v1`. Mailpit at `E2E_MAILPIT_URL`
(default `http://localhost:8025`). Seed users are those of `api/seeds/demo.py` (`web/e2e/demo-users.ts`, drift is a
vitest failure). The suite creates its own data through the API with unique tokens and never needs seeded suppliers.
`/` keeps its P00 content (the P00 smoke test still passes); only the screens below require a session. Cookies are
`Secure` and must work over `http://localhost`.

### 5.1 Routes and shell

| Route | Page |
| --- | --- |
| `/login` | h1 `Sign in`; labels `Email`, `Password`; button `Sign in`; link `Forgot password?` -> `/login/reset`; failure shows `role=alert` with text containing `email or password` and `try again` (same text for unknown email); success goes to `/suppliers` |
| `/login/reset` | h1; label `Email`, button `Send reset code`; then `role=status` containing `code` (identical for unknown emails); then labels `Code`, `New password`, button `Set new password`; success `role=status` containing `password` and a link `Sign in` |
| `/suppliers` | h1 `Suppliers`; link `Add supplier` (absent for the Viewer); searchbox `Search suppliers`; selects labelled `Status` (`All statuses`, `Approved`, `Approved with action plan`, `On watch`, `Blocked`, `Inactive`), `Category` (`All categories`, `Raw material`, `Bought-out`, `Job work`, `Service`), `Sort by` (`Name`, `Code`, `Recently updated`); checkbox `Show archived`; `role=table` named `Suppliers` (also on a 360 px phone) with rows whose accessible name contains the cells; the name cell is a link to `/suppliers/{id}`; status chip `data-testid="status-chip"` with `data-variant="outlined"`, transparent background, visible border, text = status label; button `Load more` while `next_cursor` is set (page size 50); text `No suppliers match ...` when empty; search/filter/sort re-query the API |
| `/suppliers/new` | h1 `Add supplier`; labels `Code`, `Name`, `GSTIN`, `City`, `State`, `Category`, `Status` (placeholder option `Choose a status`); button `Create supplier`; invalid fields get `aria-invalid="true"` and text (GSTIN error contains `15 letters or digits`); success opens `/suppliers/{id}` |
| `/suppliers/{id}` | h1 = supplier name; the chip; the reason text of the last status change; button `Change status` (disabled without can_approve) opening `dialog` named `Change status` with labels `New status`, `Reason`, buttons `Change status` (disabled until a non-blank reason) and `Cancel`; h2 `Contacts`; button `Add contact` opening `dialog` `Add contact` (labels `Name`, `Role`, `Mobile`, `Email`, button `Add contact`); `role=table` `Contacts`, a row per contact with badge text `Needs verification` (when `needs_reverification`) or `Disabled`, and a per-row button named `Disable <contact name>` opening `dialog` `Disable contact` (label `Reason`, button `Disable contact`) |
| `/parts` | h1 `Parts` (reachable from the main navigation) |
| `/imports` | h1 `Imports`; link `New import`; `role=table` `Imports` with a row per batch (file name, entity, status label such as `Completed`) |
| `/imports/new` | h1 `New import`; `list` named `Import steps` with items `Upload, Map columns, Validate, Preview, Confirm, Result` (`aria-current="step"` on the current one). Upload: h2 `Upload file`, select `What are you importing?` (`Suppliers`, `Parts`, `Supplier parts`), `input[type=file]`, the chosen file name shown, button `Upload file` (the browser PUTs to the presigned URL, see 5.4). Map: h2 `Map columns`, one select per target field labelled with the field label (`Code, Name, GSTIN, City, State, Category` for suppliers) listing the file's columns and an option `Not in file`; button `Validate file` disabled while a required field is `Not in file`. Validate: `progressbar` while the job runs. Preview: h2 `Preview`, `region` named `Import summary` containing `dt`/`dd` pairs `Received, Valid, Duplicates, Errors, Unmapped, Needs review` (and `Imported` on the result), `tablist` with tabs `Errors (n)`, `Duplicates (n)`, `Unmapped (n)`, `Needs review (n)` (plus `Valid (n)`), a `tabpanel` table with one row per row (row number and reason), button `Continue to confirm`. Confirm: h2 `Confirm import`; when any non-valid row exists a checkbox whose name contains `valid rows only` and `Import rows` stays disabled until it is checked; button `Cancel import` on every step before confirm; the same-file warning is a `role=alert` containing `uploaded before` with a link named `previous import`, shown on the Map step and not blocking. Result: h2 `Import complete`, the summary region with `Imported`, link `Download report` (the `.xlsx` report), link `View suppliers`. A Viewer opening it sees a `role=alert` containing `permission` and no `Upload file` button |
| shell | a `navigation` named `Main navigation` (left nav >= 640 px, bottom bar below, spanning the screen width) with links `Suppliers`, `Parts`, `Imports`; button `Sign out`; on a 360 px phone no horizontal scroll, inputs >= 16 px font and >= 48 px high, primary buttons and list links >= 48 px high |
| locale | cookie `ql_locale=hi` sets `<html lang="hi">` and Devanagari headings |

`data-testid` is used only for `status-chip` (no accessible name can identify a chip) and the P00 `app-nav`.

### 5.2 Web modules (vitest, node environment, no DOM)

Components take already translated strings as props and use no `next-intl` hooks, so they render with
`react-dom/server`.

| Module | Exports |
| --- | --- |
| `@/lib/format` | `formatIndianNumber(n)` (`420000` -> `4,20,000`, negatives with `-`), `formatInr(paise)` (`42000000` -> `₹4,20,000`, `12345` -> `₹123.45`), `formatDate(isoInstant, timeZone)` (`3 Oct 2026`, plant timezone) |
| `@/lib/reason` | `REASON_MAX = 2000`, `isValidReason(s)` (trimmed length 1-2000), `reasonError(s)` -> `'required' \| 'too_long' \| null` |
| `@/lib/import-wizard` | `WIZARD_STEPS = ['upload','map','validate','preview','confirm','result']`, `needsPartialConfirmation(batch counts)`, `canConfirm({counts, acceptPartial})` (false for zero rows, or partial without the tick), `missingRequiredFields(targetFields, mapping)`, `reconciles(counts)`; counts use the API names `rows_received ... rows_review` |
| `@/lib/problem` | `describeProblem(body: unknown) -> {title, detail, fields: Record<string,string>}`; never "Something went wrong"; keeps `request_id` in the text for a 500 |
| `@/lib/http` | `readCookie(header, name)` (URL-decoded), `commandHeaders({csrf, idempotencyKey?})` (`Content-Type`, `X-CSRF-Token` only when set, `Idempotency-Key` only when given), `newIdempotencyKey()` (hyphenated UUID) |
| `@/components/status-chip` | `StatusChip({kind: 'supplier-status', value, label})` renders `data-testid="status-chip" data-variant="outlined" data-status={value}` with the label as its whole text, escaped, no risk styling |
| `@/components/reason-dialog` | `ReasonDialog({open, title, consequence, reasonLabel, actionLabel, cancelLabel, onConfirm(reason), onCancel})`: nothing when closed; `role="dialog" aria-modal="true" aria-labelledby` -> title element; consequence text; `<label for>` + `<textarea required maxLength=2000>`; confirm button text = `actionLabel`, `disabled` until the reason is valid, never autofocused |
| i18n | namespaces `common, login, suppliers, contacts, parts, imports` exist in `messages/en.json` and `messages/hi.json` with identical keys, no empty values, phrases (containing a space) translated into Devanagari in Hindi |

### 5.3 Playwright projects

`desktop-1440` runs every spec except `*.phone.spec.ts`; `phone-360` (Pixel 5 at 360 x 740) runs `smoke.spec.ts` and
`*.phone.spec.ts` only (`playwright.config.ts` was changed accordingly, `actionTimeout` 15 s). Import specs set a 180 s
timeout; waits use web-first assertions, no fixed sleeps.

### 5.4 Browser uploads (decision A-120)

The wizard uploads from the browser by `PUT` to the presigned quarantine URL. Decision A-120: the CSP `connect-src` in
`web/src/proxy.ts` adds the configured public S3 origin (`QL_S3_PUBLIC_ENDPOINT_URL`), presigned URLs are built on that
public origin, and the bucket CORS allows only the web origin and `PUT` (with `Content-Type`). There is no upload proxy.
The E2E upload tests in `web/e2e/imports.spec.ts` are the only tests of this; they cannot pass without it.

## 6. Ambiguities and the assumption each test makes

1. **(Decided A-116, tested.)** Who may create a supplier with which status. A-06 says only that the status is required on create. A Quality user
   without can_approve could create a `blocked` supplier and bypass the +CA gate of the status command. Tests create
   non-`approved` suppliers with the approver and never assert who may create what. Needs a human decision.
2. **(Decided A-118, tested.)** Natural-key matching across keys. A file row with a GSTIN never matches an existing supplier that has the same
   name and city but no GSTIN (and the reverse), so such rows import as new. Not tested; flagged.
3. **Exactly 180 days.** `needs_reverification` is tested at 179 d, 180 d minus 1 h, 180 d plus 1 h and 181 d, not at
   exactly 180 days (plan says "older than 180", the blueprint says "unverified for 180 days").
4. **(Decided A-117, tested.)** `supplier_parts.status`. A-75 gives `active`/`inactive`, but `/supplier-parts/{id}/update` may not accept `status`
   (INV-PLT-06 route scan fails on any `status` property of an `/update` body). The tests send no `status` on update and
   expect 422 if it is sent. How a link becomes `inactive` is open (archive is the unlink).
5. **(Decided A-119, tested.)** Re-linking after unlink. `customer_parts` and `supplier_parts` are unique per pair even when archived, so an
   archived link blocks a new one. Not tested.
6. **Mapping edits.** Re-mapping a `validated` batch is neither required nor forbidden by the tests.
7. **`q` is contains, not prefix; `archived=true` includes archived rows** (the tests do not assert that live rows are
   absent from an `archived=true` list).
8. **Phone OTP and clock.** Mobile OTP is verified through the in-process fake channel; expiry is simulated by deleting the
   `otp:*` key (a time machine cannot move Redis TTLs).
9. **`contact.revoke_access` / `contact.replaced` argument shapes** (section 1) and the `imports.*` actor names are
   assumptions the implementer may change only by telling QA.
10. **CSV numbers.** A CSV cell `1234.0` is text and stays `1234.0`; float cleaning applies to numeric xlsx cells only.
11. **Clean exit for stale jobs.** A job whose batch is not visible or not in the expected status returns without error.
