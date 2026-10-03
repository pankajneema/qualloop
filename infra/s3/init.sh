#!/bin/sh
# One-shot: create the two private buckets (aws-cli image). Idempotent.
set -eu
export AWS_ACCESS_KEY_ID="${QL_S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${QL_S3_SECRET_KEY}" AWS_DEFAULT_REGION=us-east-1
ENDPOINT="${QL_S3_ENDPOINT_URL:-http://s3:8333}"
for b in qualloop-files qualloop-quarantine; do
  aws --endpoint-url "$ENDPOINT" s3api head-bucket --bucket "$b" 2>/dev/null \
    || aws --endpoint-url "$ENDPOINT" s3api create-bucket --bucket "$b" >/dev/null
  echo "bucket ready: $b"
done
