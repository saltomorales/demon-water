#!/usr/bin/env bash
# Web start command for the vector app on Upsun Fixed.
set -euo pipefail

: "${CH_VECTOR_PASSWORD:?set env:CH_VECTOR_PASSWORD as an Upsun variable}"

# ClickHouse endpoint from the "clickhouse" relationship; vector.yaml reads these.
rel="$(echo "$PLATFORM_RELATIONSHIPS" | base64 -d | jq -c '.clickhouse[0]')"
export CLICKHOUSE_URL="http://$(jq -r .host <<<"$rel"):$(jq -r .port <<<"$rel")"
export CLICKHOUSE_USERNAME=vector
export CLICKHOUSE_PASSWORD="$CH_VECTOR_PASSWORD"

# Vector >= 0.59 needs an explicit opt-in to interpolate env vars (older versions do it by default
# and reject the flag). The config is ours, so opting in is safe.
flags=()
if vector --help 2>/dev/null | grep -q -- --dangerously-allow-env-var-interpolation; then
  flags+=(--dangerously-allow-env-var-interpolation)
fi
exec vector "${flags[@]}" --config /app/vector.yaml
