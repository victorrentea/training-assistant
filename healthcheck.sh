#!/bin/bash
# Production health check for interact.victorrentea.ro
# Exit 0 = healthy, Exit 1 = failure detected

BASE_URL="https://interact.victorrentea.ro"
FAILED=0
DETAILS=""

# Load credentials if available
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/secrets.env" ]; then
  source "$SCRIPT_DIR/secrets.env"
fi
HOST_USER="${HOST_USERNAME:-host}"
HOST_PASS="${HOST_PASSWORD:-host}"

check() {
  local name="$1" url="$2" expect_status="$3" auth="$4"
  local start end elapsed status body

  start=$(date +%s%N 2>/dev/null || python3 -c 'import time; print(int(time.time()*1e9))')

  if [ -n "$auth" ]; then
    body=$(curl -s -o /dev/null -w '%{http_code}\n%{time_total}' --max-time 10 -u "$HOST_USER:$HOST_PASS" "$url")
  else
    body=$(curl -s -o /dev/null -w '%{http_code}\n%{time_total}' --max-time 10 "$url")
  fi

  status=$(echo "$body" | head -1)
  elapsed=$(echo "$body" | tail -1)

  if [ "$status" -ge 500 ] 2>/dev/null; then
    FAILED=1
    DETAILS="${DETAILS}\n  FAIL $name: HTTP $status (expected $expect_status) [${elapsed}s]"
    # Get response body for debugging
    if [ -n "$auth" ]; then
      local err_body=$(curl -s --max-time 5 -u "$HOST_USER:$HOST_PASS" "$url" | head -c 500)
    else
      local err_body=$(curl -s --max-time 5 "$url" | head -c 500)
    fi
    DETAILS="${DETAILS}\n  Body: $err_body"
  elif [ "$status" != "$expect_status" ] && [ "$expect_status" != "any" ]; then
    FAILED=1
    DETAILS="${DETAILS}\n  FAIL $name: HTTP $status (expected $expect_status) [${elapsed}s]"
  else
    DETAILS="${DETAILS}\n  OK   $name: HTTP $status [${elapsed}s]"
  fi
}

# Run checks
check "Participant page" "$BASE_URL/" "200"
check "Host page (no 5xx)" "$BASE_URL/host" "any"
check "API status"       "$BASE_URL/api/status" "200"
check "API suggest-name" "$BASE_URL/api/suggest-name" "200"

# JSON validation for /api/status
api_body=$(curl -s --max-time 10 "$BASE_URL/api/status")
if ! echo "$api_body" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  FAILED=1
  DETAILS="${DETAILS}\n  FAIL API status: invalid JSON response: ${api_body:0:200}"
fi

# Output
if [ "$FAILED" -eq 0 ]; then
  echo "OK - Production healthy $(date '+%H:%M:%S')"
  echo -e "$DETAILS" | grep -v '^$'
  exit 0
else
  echo "FAIL - Production issues detected $(date '+%H:%M:%S')"
  echo -e "$DETAILS" | grep -v '^$'
  exit 1
fi
