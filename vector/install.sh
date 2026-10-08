#!/usr/bin/env bash
# Build hook: install the official static Vector binary into /app/bin.
# Same version as local `vector test`, so unit tests cover what runs in production
# (Nix on composable:26.05 ships 0.55). Bump VECTOR_VERSION and VECTOR_SHA256 together.
set -euo pipefail

VECTOR_VERSION="0.59.0"
VECTOR_SHA256="a8dbc43c18ae25d0b23a712c9262f3aad904e352b1db5e7db1d9c4aecab59496"
TGZ="vector-${VECTOR_VERSION}-x86_64-unknown-linux-musl.tar.gz"
URL="https://github.com/vectordotdev/vector/releases/download/v${VECTOR_VERSION}/${TGZ}"

tmp="$(mktemp -d)"
cd "$tmp"
curl -fsSL -o "$TGZ" "$URL"
echo "${VECTOR_SHA256}  ${TGZ}" | sha256sum -c -

tar -xzf "$TGZ"
mkdir -p "$PLATFORM_APP_DIR/bin"
install -m 0755 "$(find . -path '*/bin/vector' -type f | head -n1)" "$PLATFORM_APP_DIR/bin/vector"
cd "$PLATFORM_APP_DIR"
rm -rf "$tmp"

"$PLATFORM_APP_DIR/bin/vector" --version
