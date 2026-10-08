#!/usr/bin/env bash
# Build hook: install Grafana plugins into the (read-only at runtime) app dir.
set -euo pipefail

GRAFANA_HOME="$(dirname "$(readlink -f "$(command -v grafana)")")/../share/grafana"

grafana cli \
  --homepath "$GRAFANA_HOME" \
  --pluginsDir "$PLATFORM_APP_DIR/.grafana-plugins" \
  plugins install grafana-clickhouse-datasource
