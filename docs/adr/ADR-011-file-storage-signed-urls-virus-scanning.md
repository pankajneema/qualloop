# ADR-011 — File storage, signed URLs, virus scanning

- Status: Accepted (2026-10-03, design only); still pending — ClamAV needs its own process/container → **requires human approval (CLAUDE.md §5, A-47)**
- Spec: §20.2 (PDF/JPG/PNG ≤ 20 MB, content-type check + virus scan), §21.1 (private buckets, signed URLs ≤ 15 min), §22 (S3-compatible, Indian region)

## Context
Files: NCR photos, supplier documents/certificates, 8D evidence, import spreadsheets, generated PDFs and Excel exports.
Uploads come from internal users and from suppliers on slow phones.

## Options considered
| Concern | Options | Chosen |
| --- | --- | --- |
| Upload path | through API (stream) vs **presigned PUT direct to storage** | presigned PUT — no large bodies through api; resumable by retry on slow 3G |
| Buckets | single vs **quarantine + clean** | two buckets: uploads land in `quarantine`, promoted after scan |
| Content-type check | trust header vs **magic-byte sniff** (`filetype` lib) + extension + declared type must agree | sniff |
| Virus scan | none; **ClamAV `clamd` sidecar** (free, self-run); AWS GuardDuty Malware Protection for S3 (paid managed) | ClamAV sidecar if approved; GuardDuty as the managed alternative for the human to choose |
| Downloads | public URLs vs **presigned GET ≤ 15 min** | presigned GET, `Content-Disposition: attachment` for documents, `inline` for images only |

## Decision
1. Key layout: `t/{tenant_id}/{kind}/{object_id}/{uuid7}.{ext}` (kind ∈ `ncr`, `doc`, `evidence`, `import`, `report`, `export`).
   The file service rejects any key whose tenant prefix ≠ caller tenant.
2. `POST /api/v1/files/upload-url` validates purpose, declared content type and size (≤ 20 MB; imports: xlsx/csv ≤ 20 MB) →
   presigned PUT (quarantine bucket, 15 min, `Content-Length` and `Content-Type` conditions).
3. Register command stores the key with `pending_scan` (documents) or a pending flag in the domain flow; worker `ai`
   queue job `files.scan`: download, magic-byte check, `clamd INSTREAM` scan, SHA-256, copy to private bucket, delete
   from quarantine, mark `available`; failures → `quarantined`, user-visible message (what happened · what we did · what to do).
4. Fail closed: a file that has not passed scan is never downloadable or sent to AI (INV-DOC-10).
   If ClamAV is not approved, files stay `pending_scan` and the P01 gate cannot pass — the human must choose ClamAV,
   GuardDuty, or explicitly accept "content-type check only" as a recorded risk.
5. Buckets private, Block Public Access, SSE-KMS, versioning on the files bucket; quarantine lifecycle 7 days;
   exports/reports lifecycle 30 days (regenerable).
6. Local: MinIO with the same two buckets.

## Consequences
- Worker image or sidecar must include `clamd` with signature updates (`freshclam`) — memory ≈ 1–1.5 GB.
- Extra copy per upload (quarantine → files) — negligible at Stage 1 volume.

## Revisit when
- Scan queue lag > 2 min p95, or ClamAV memory cost exceeds the worker task size (→ GuardDuty or dedicated scanner service), or
- storage > 1 TB (→ lifecycle tiering).
