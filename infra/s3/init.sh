#!/bin/sh
# One-shot: create the two private buckets and set CORS on the quarantine bucket (aws-cli image). Idempotent.
# Browser uploads (A-120): the web app PUTs to a presigned quarantine URL, so the bucket allows exactly one origin
# (the web origin, QL_WEB_ORIGIN, default http://localhost:3000), method PUT, and the headers a presigned PUT sends.
# No wildcard origin. Staging/prod CORS is set in IaC (P09), not here.
set -eu
export AWS_ACCESS_KEY_ID="${QL_S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${QL_S3_SECRET_KEY}" AWS_DEFAULT_REGION=us-east-1
ENDPOINT="${QL_S3_ENDPOINT_URL:-http://s3:8333}"
WEB_ORIGIN="${QL_WEB_ORIGIN:-http://localhost:3000}"
BUCKET_Q="${QL_S3_BUCKET_QUARANTINE:-qualloop-quarantine}"
case "$WEB_ORIGIN" in
  ""|*"*"*) echo "QL_WEB_ORIGIN must be one explicit origin, got '$WEB_ORIGIN'" >&2; exit 1 ;;
esac
for b in "${QL_S3_BUCKET_FILES:-qualloop-files}" "$BUCKET_Q"; do
  aws --endpoint-url "$ENDPOINT" s3api head-bucket --bucket "$b" 2>/dev/null \
    || aws --endpoint-url "$ENDPOINT" s3api create-bucket --bucket "$b" >/dev/null
  echo "bucket ready: $b"
done
aws --endpoint-url "$ENDPOINT" s3api put-bucket-cors --bucket "$BUCKET_Q" --cors-configuration \
  "{\"CORSRules\":[{\"AllowedOrigins\":[\"$WEB_ORIGIN\"],\"AllowedMethods\":[\"PUT\"],\"AllowedHeaders\":[\"Content-Type\",\"Content-Length\"],\"MaxAgeSeconds\":600}]}"
echo "cors set: $BUCKET_Q allows $WEB_ORIGIN (PUT)"
