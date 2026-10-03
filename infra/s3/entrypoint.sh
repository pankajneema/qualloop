#!/bin/sh
# Local/CI S3 endpoint (SeaweedFS). Identity comes from QL_S3_ACCESS_KEY / QL_S3_SECRET_KEY, so anonymous
# requests are rejected (403). Buckets without their own CORS rules (files) only answer the web origin (A-120). Dev/CI only; staging/prod use the cloud provider's object storage.
set -eu
cat > /tmp/s3.json <<JSON
{"identities":[{"name":"qualloop","credentials":[{"accessKey":"${QL_S3_ACCESS_KEY}","secretKey":"${QL_S3_SECRET_KEY}"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
JSON
exec weed server -dir=/data -master.volumeSizeLimitMB=64 -volume.max=50 -s3 -s3.port=8333 -s3.config=/tmp/s3.json -s3.allowedOrigins="${QL_WEB_ORIGIN:-http://localhost:3000}" -ip.bind=0.0.0.0
