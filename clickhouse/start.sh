#!/usr/bin/env bash
# Web start command for the clickhouse app on Upsun Fixed.
set -euo pipefail

for v in CH_ADMIN_PASSWORD CH_VECTOR_PASSWORD CH_GRAFANA_PASSWORD; do
  : "${!v:?set env:$v as an Upsun sensitive variable}"
done

mkdir -p /app/.clickhouse-data/tmp /app/.clickhouse-data/user_files /app/.clickhouse-data/format_schemas

# The app dir is read-only at runtime; ClickHouse writes preprocessed configs under <path> (the mount).
exec /app/bin/clickhouse server --config-file=/app/config.xml
