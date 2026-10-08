#!/usr/bin/env bash
# Web start command for the vector app on Upsun Fixed.
set -euo pipefail

: "${CH_VECTOR_PASSWORD:?set env:CH_VECTOR_PASSWORD as an Upsun variable}"

# ClickHouse endpoint from the "clickhouse" relationship; vector.yaml reads these.
rel="$(echo "$PLATFORM_RELATIONSHIPS" | base64 -d | jq -c '.clickhouse[0]')"
export CLICKHOUSE_URL="http://$(jq -r .host <<<"$rel"):$(jq -r .port <<<"$rel")"
export CLICKHOUSE_USERNAME=vector
export CLICKHOUSE_PASSWORD="$CH_VECTOR_PASSWORD"
export VECTOR_TENANTS_FILE=/app/tenants.csv

# Vector >= 0.59 needs an explicit opt-in to interpolate env vars; the config is ours.
exec /app/bin/vector --dangerously-allow-env-var-interpolation --config /app/vector.yaml
