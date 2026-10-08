#!/usr/bin/env bash
# Web start command for the grafana app on Upsun.
set -euo pipefail

GRAFANA_HOME="$(dirname "$(readlink -f "$(command -v grafana)")")/../share/grafana"

export GF_SERVER_HTTP_ADDR=0.0.0.0
export GF_SERVER_HTTP_PORT="$PORT"
# Admin password comes from the Upsun variable env:GF_SECURITY_ADMIN_PASSWORD.
: "${GF_SECURITY_ADMIN_PASSWORD:?set env:GF_SECURITY_ADMIN_PASSWORD as an Upsun variable}"

mkdir -p "$GF_PATHS_DATA" "$GF_PATHS_LOGS"

exec grafana server --homepath "$GRAFANA_HOME"
