#!/usr/bin/env bash
# Run Vector unit tests: ./vector/test.sh
# Uses the test allowlist (tests/tenants.csv) and dummy sink settings.
set -euo pipefail
cd "$(dirname "$0")"

export PORT=8080
export VECTOR_TENANTS_FILE=tests/tenants.csv
export CLICKHOUSE_URL=http://127.0.0.1:8123
export CLICKHOUSE_USERNAME=test
export CLICKHOUSE_PASSWORD=test

exec vector test --dangerously-allow-env-var-interpolation vector.yaml tests/*.yaml
