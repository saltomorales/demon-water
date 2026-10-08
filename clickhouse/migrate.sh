#!/usr/bin/env bash
# post_start: wait for ClickHouse, then apply schema/*.sql in order.
# Every statement must be idempotent (IF NOT EXISTS), since this runs on every start.
set -euo pipefail

ch() {
  clickhouse client --host 127.0.0.1 --port 9000 \
    --user admin --password "$CH_ADMIN_PASSWORD" "$@"
}

for _ in $(seq 1 60); do
  ch --query "SELECT 1" >/dev/null 2>&1 && break
  sleep 1
done
ch --query "SELECT 1" >/dev/null

for f in /app/schema/*.sql; do
  [ -e "$f" ] || continue
  echo "migrate: $f"
  ch --multiquery < "$f"
done
