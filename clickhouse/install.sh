#!/usr/bin/env bash
# Build hook: install the official static ClickHouse binary into /app/bin.
# The Nix `clickhouse` package crashes on start in Upsun containers
# ("Cannot allocate ThreadStack", errno 22), so we use the upstream LTS build.
set -euo pipefail

CH_VERSION="26.8.20.9"
CH_TAG="v${CH_VERSION}-lts"
TGZ="clickhouse-common-static-${CH_VERSION}-amd64.tgz"
URL="https://github.com/ClickHouse/ClickHouse/releases/download/${CH_TAG}/${TGZ}"

tmp="$(mktemp -d)"
cd "$tmp"
curl -fsSL -o "$TGZ" "$URL"
curl -fsSL -o "$TGZ.sha512" "$URL.sha512"
sha512sum -c "$TGZ.sha512"

tar -xzf "$TGZ"
mkdir -p "$PLATFORM_APP_DIR/bin"
install -m 0755 "$(find . -path '*/usr/bin/clickhouse' -type f | head -n1)" "$PLATFORM_APP_DIR/bin/clickhouse"
cd "$PLATFORM_APP_DIR"
rm -rf "$tmp"

"$PLATFORM_APP_DIR/bin/clickhouse" --version
