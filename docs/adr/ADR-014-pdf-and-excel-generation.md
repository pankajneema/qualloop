# ADR-014 — PDF and Excel generation

- Status: Proposed
- Spec: §16 C14 (Monthly Supplier Quality Report PDF, supplier report card, Excel export from every list), §22 (PDF: HTML → PDF; PDFs in worker queue), §8 C3 (reconciliation report Excel)

## Options considered
| Concern | Options | Chosen | Why |
| --- | --- | --- | --- |
| HTML → PDF | headless Chromium (Playwright); **WeasyPrint** | WeasyPrint | pure-Python + Pango/HarfBuzz (correct Devanagari shaping), no browser process in workers, deterministic output |
| Templates | **Jinja2** HTML + print CSS using the same token values (exported to CSS variables at build) | — | |
| Charts in PDF | **server-side SVG** generated in Python (simple bars/lines) | — | no JS in PDFs |
| Excel read | **openpyxl** (xlsx), stdlib `csv` | — | imports |
| Excel write | **openpyxl** write-only mode | — | streaming for large lists |

## Decision
- Reports render in the `reports` queue; `POST /reports/...` returns `202 {report_key}`; output stored under
  `t/{tenant}/report/...`; `GET /reports/{report_key}` returns status + signed URL. Job status kept in Redis (TTL 24 h);
  the object's existence is the durable signal.
- Report numbers come from the same `scoring` calculators as the API (P08 test: PDF values equal API values).
- Excel exports: permission-checked (Viewer denied, A-70), logged to `activity_log`, every cell that starts with
  `= + - @ \t \r` is prefixed with `'` (formula-injection neutralisation, INV-IMP-08).
- Fonts embedded in PDFs: IBM Plex Sans / Devanagari / Mono.

## Consequences
- Worker image needs Pango/cairo system libraries (≈ 60 MB).

## Revisit when
- A report layout needs CSS WeasyPrint does not support, or PDF render > 30 s p95.
