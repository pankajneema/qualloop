#!/usr/bin/env bash
# Warm the Next.js dev server: request every app route once so each is compiled
# before Playwright runs. A dummy ql_session cookie gets past the proxy login
# redirect (it only checks cookie presence), so the real route compiles. Any HTTP status (404 included) counts as warmed; the
# step fails only if the server is unreachable (curl exit != 0).
# Usage: infra/scripts/warm_web.sh [base_url]   (default http://localhost:3000)
set -uo pipefail

BASE="${1:-${QL_WEB_URL:-http://localhost:3000}}"
TIMEOUT="${WARM_TIMEOUT:-120}"
ID="00000000-0000-0000-0000-000000000000"
ROUTES=(
  /
  /login
  /login/reset
  /suppliers
  /suppliers/new
  "/suppliers/$ID"
  "/suppliers/$ID/edit"
  /parts
  /parts/new
  "/parts/$ID"
  /imports
  /imports/new
  "/imports/$ID"
)

fail=0
total_start=$SECONDS
for r in "${ROUTES[@]}"; do
  out=$(curl -s -o /dev/null -H "Cookie: ql_session=warmup" --max-time "$TIMEOUT" --connect-timeout 10 \
        -w '%{http_code} %{time_total}s' "$BASE$r")
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "warm: $r UNREACHABLE (curl exit $rc)" >&2
    fail=1
  else
    echo "warm: $r -> $out"
  fi
done
echo "warm: done in $((SECONDS - total_start))s"
exit $fail
