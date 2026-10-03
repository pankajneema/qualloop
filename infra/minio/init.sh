#!/bin/sh
# One-shot bucket creation (private buckets). Run by the minio-init compose service with minio/mc.
set -eu
PATH="$PATH:/opt/bitnami/minio-client/bin"
mc alias set local "${MINIO_ENDPOINT:-http://minio:9000}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"
for b in qualloop-files qualloop-quarantine; do
  mc mb --ignore-existing "local/$b"
  mc anonymous set none "local/$b"
done
echo "buckets ready"
