#!/usr/bin/env bash
# Web start command for the grafana app on Upsun Fixed.
set -euo pipefail

GRAFANA_HOME="$(dirname "$(readlink -f "$(command -v grafana)")")/../share/grafana"

export GF_SERVER_HTTP_ADDR=0.0.0.0
export GF_SERVER_HTTP_PORT="$PORT"
: "${GF_SECURITY_ADMIN_PASSWORD:?set env:GF_SECURITY_ADMIN_PASSWORD as an Upsun variable}"
: "${CH_GRAFANA_PASSWORD:?set env:CH_GRAFANA_PASSWORD as an Upsun variable}"

# Read-only ClickHouse connection from the "clickhouse" relationship; used by provisioning/datasources.
rel="$(echo "$PLATFORM_RELATIONSHIPS" | base64 -d | jq -c '.clickhouse[0]')"
export CLICKHOUSE_HOST="$(jq -r .host <<<"$rel")"
export CLICKHOUSE_PORT="$(jq -r .port <<<"$rel")"
export CLICKHOUSE_USERNAME=grafana
export CLICKHOUSE_PASSWORD="$CH_GRAFANA_PASSWORD"

mkdir -p "$GF_PATHS_DATA" "$GF_PATHS_LOGS"

exec grafana server --homepath "$GRAFANA_HOME"
