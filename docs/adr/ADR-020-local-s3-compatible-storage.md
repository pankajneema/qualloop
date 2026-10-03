# ADR-020 — Local S3-compatible storage for dev and CI

- Status: Accepted (2026-10-03, human decision)
- Spec: §22 (S3-compatible storage), §21.1 (private buckets), CLAUDE.md §5 (no paid services)
- Supersedes: the `minio/minio` choice in REPO_LAYOUT.md §3 and ADR-011 item 6

## Context
Dev and CI need an S3-compatible object store with private buckets. `minio/minio` and `minio/mc` are no longer
published on Docker Hub, and the stop-gap `bitnamilegacy/minio` image receives no updates. The human asked for a
maintained replacement. Production still targets AWS S3 in ap-south-1 (ADR-011, ADR-017); this ADR is dev/CI only.

## Options considered
| Option | Maintained | Licence | Fit |
| --- | --- | --- | --- |
| `bitnamilegacy/minio` | No (legacy, frozen) | AGPL-3.0 | works, but no security updates |
| SeaweedFS (`chrislusf/seaweedfs`) | Yes — release 4.48 on 2026-09-28; Docker Hub tags updated 2026-10-02 | Apache-2.0 | single container, S3 gateway, identities from config |
| Garage | Yes | AGPL-3.0 | needs cluster layout setup before use |
| LocalStack | Yes | mixed (community/pro) | heavier, broader than needed |

## Decision
SeaweedFS `chrislusf/seaweedfs:4.48`, pinned by digest
`sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`.

| Item | Value |
| --- | --- |
| Compose service | `s3` (port 8333); one-shot `s3-init` using `amazon/aws-cli:2.34.0` (pinned by digest) |
| Files | `infra/s3/entrypoint.sh` (S3 identity from `QL_S3_ACCESS_KEY` / `QL_S3_SECRET_KEY`), `infra/s3/init.sh` (buckets) |
| Buckets | `qualloop-files`, `qualloop-quarantine` — private |
| Endpoint | `http://s3:8333` in compose; `http://localhost:8333` from host and CI |
| Healthcheck | master answers and anonymous S3 request returns 403 |
| CI | started as job steps in `api-test` (a service container cannot take the custom entrypoint) |

Verified locally 2026-10-03: anonymous GET bucket / object / list → 403; authenticated `aws s3 ls` lists both buckets;
`make up`, `make test`, `make ci`, `make e2e` green.

## Consequences
- App code talks only to the S3 API (boto3), so swapping the dev store does not touch application code.
- SeaweedFS S3 compatibility is not 100 %; any feature the app needs (presigned PUT/GET, content-type, size limits)
  is covered by integration tests in P01 against this store, and against AWS S3 in staging (P09).

## Revisit when
SeaweedFS stops releasing for > 6 months, or an S3 feature used by the app behaves differently from AWS S3 in tests.
