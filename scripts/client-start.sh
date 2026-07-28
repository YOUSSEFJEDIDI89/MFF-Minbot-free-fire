#!/usr/bin/env bash
# client-start.sh — minimal client launcher for Termux / Android.
#
# Use this when you want to CONNECT to a VortexVPN server from your
# phone, not run the server itself. It installs only the bare minimum
# (no Flask, no server code paths), then runs tunnel_client.
#
# Usage:
#   ./scripts/client-start.sh SERVER_IP PORT USERNAME PASSWORD
#
# Example:
#   ./scripts/client-start.sh 192.168.1.50 4433 alice MyPassword123

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$HERE")"
cd "$PROJECT_DIR"

VENV_DIR="$PROJECT_DIR/venv"
PYTHON="$VENV_DIR/bin/python"

# ---------------- venv ----------------
if [ ! -x "$PYTHON" ]; then
  echo "[1/3] creating venv..."
  python3 -m venv "$VENV_DIR"
fi

# ---------------- minimal deps (client only) ----------------
echo "[2/3] installing minimal client deps..."
"$PYTHON" -m pip install --quiet --upgrade pip
# Client needs only pycryptodome (or cryptography) — no Flask, no gunicorn
"$PYTHON" -m pip install --quiet pycryptodome 2>&1 | tail -1 || {
  echo "[X] failed to install pycryptodome"
  echo "    on Termux: pkg install python python-dev"
  exit 1
}

# ---------------- run client ----------------
SERVER_IP="${1:-}"
SERVER_PORT="${2:-4433}"
USERNAME="${3:-}"
PASSWORD="${4:-}"

if [ -z "$SERVER_IP" ] || [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
  cat <<EOF
usage: $0 SERVER_IP [PORT] USERNAME PASSWORD

example:
  $0 192.168.1.50 4433 alice MyPassword123

Get SERVER_IP and PORT from your server's web panel (/connect page).
Create USERNAME and PASSWORD in the server's web panel (/users page).
EOF
  exit 1
fi

echo "[3/3] connecting to $SERVER_IP:$SERVER_PORT as $USERNAME..."
echo "      (Ctrl+C to disconnect)"
echo ""
exec "$PYTHON" -m vortexvpn.core.tunnel_client \
  --host "$SERVER_IP" \
  --port "$SERVER_PORT" \
  --user "$USERNAME" \
  --password "$PASSWORD"
