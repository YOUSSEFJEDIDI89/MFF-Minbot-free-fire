#!/usr/bin/env bash
# start-dev.sh - run VortexVPN in foreground for development.
#
# Loads config from ./configs/config.toml, prints logs to stderr,
# and starts the Flask dev server on 127.0.0.1:8080.

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$(dirname "$HERE")"

PYTHON="${PYTHON:-python3}"
if [ -d "venv" ]; then
    PYTHON="$(pwd)/venv/bin/python"
fi

echo "[dev] using $PYTHON"
echo "[dev] load config from configs/config.toml (or env vars)"
exec "$PYTHON" -m vortexvpn.web
