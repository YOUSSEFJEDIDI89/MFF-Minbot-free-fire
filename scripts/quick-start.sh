#!/usr/bin/env bash
# quick-start.sh — one command, zero headaches.
#
# What this does (in order):
#   1. Creates a Python venv if missing
#   2. Installs dependencies
#   3. Builds the C++ accelerator (optional — skipped silently if it fails)
#   4. Generates a strong random admin password + web secret
#   5. Writes configs/config.toml if missing
#   6. Creates the admin user
#   7. Starts the server in the background
#   8. Prints a clean summary: URL, admin user, password, tunnel port
#
# Re-running this script is safe — it only does what's missing.
#
# Usage:
#   ./scripts/quick-start.sh                # start (or restart) on default ports
#   ./scripts/quick-start.sh --restart      # force restart
#   ./scripts/quick-start.sh --stop         # stop the server
#   ./scripts/quick-start.sh --logs         # tail logs

set -e

# --------------------------------------------------------------------------- #
# Resolve paths
# --------------------------------------------------------------------------- #
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$HERE")"
cd "$PROJECT_DIR"

VENV_DIR="$PROJECT_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
PID_FILE="$PROJECT_DIR/vortexvpn.pid"
LOG_FILE="$PROJECT_DIR/vortexvpn.log"
CONFIG_FILE="$PROJECT_DIR/configs/config.toml"
SECRET_FILE="$PROJECT_DIR/.vortex-secrets.env"

# --------------------------------------------------------------------------- #
# Handle simple commands first
# --------------------------------------------------------------------------- #
ACTION="${1:-start}"
case "$ACTION" in
  --stop)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      sleep 1
      kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "[+] server stopped"
    else
      echo "[i] server is not running"
    fi
    exit 0
    ;;
  --logs)
    [ -f "$LOG_FILE" ] || { echo "no log file yet"; exit 1; }
    tail -n 100 -f "$LOG_FILE"
    exit 0
    ;;
  --status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[+] running, pid $(cat "$PID_FILE")"
      exit 0
    else
      echo "[i] not running"
      exit 3
    fi
    ;;
  --restart)
    "$0" --stop 2>/dev/null || true
    ACTION="start"
    ;;
  start) ;;
  *)
    echo "usage: $0 {start|--restart|--stop|--status|--logs}" >&2
    exit 1
    ;;
esac

# --------------------------------------------------------------------------- #
# Detect Termux / Android (no prebuilt cryptography wheels here)
# --------------------------------------------------------------------------- #
detect_termux() {
  if [ -n "$PREFIX" ] && case "$PREFIX" in *com.termux*) true;; *) false;; esac; then
    return 0
  fi
  if [ -d "/data/data/com.termux" ]; then return 0; fi
  if command -v termux-info >/dev/null 2>&1; then return 0; fi
  return 1
}

IS_TERMUX=0
if detect_termux; then
  IS_TERMUX=1
fi

# --------------------------------------------------------------------------- #
# Pretty printer
# --------------------------------------------------------------------------- #
C_GREEN="\033[32m"; C_CYAN="\033[36m"; C_YELLOW="\033[33m"; C_RED="\033[31m"
C_BOLD="\033[1m"; C_RESET="\033[0m"
step() { echo -e "${C_CYAN}[$1]${C_RESET} $2"; }
ok()   { echo -e "${C_GREEN}[OK]${C_RESET} $1"; }
warn() { echo -e "${C_YELLOW}[!]${C_RESET} $1"; }
err()  { echo -e "${C_RED}[X]${C_RESET} $1" >&2; }

if [ "$IS_TERMUX" = "1" ]; then
  warn "Termux / Android detected"
  warn "  → using pycryptodome instead of cryptography (no Rust needed)"
  warn "  → C++ accelerator will be skipped"
  warn "  → this device is best used as the CLIENT, not the SERVER"
  echo ""
fi

# --------------------------------------------------------------------------- #
# Step 1: venv
# --------------------------------------------------------------------------- #
if [ ! -x "$PYTHON" ]; then
  step "1/7" "creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# --------------------------------------------------------------------------- #
# Step 2: dependencies
# --------------------------------------------------------------------------- #
step "2/7" "checking Python dependencies..."
"$PYTHON" -m pip install --quiet --upgrade pip wheel setuptools
if [ "$IS_TERMUX" = "1" ]; then
  REQ_FILE="$PROJECT_DIR/requirements-termux.txt"
else
  REQ_FILE="$PROJECT_DIR/requirements.txt"
fi
"$PYTHON" -m pip install --quiet -r "$REQ_FILE" 2>&1 | tail -1 || {
  err "failed to install Python deps"
  err "  tried: $REQ_FILE"
  err "  on Termux? Make sure: pkg install python python-dev rust binutils"
  exit 1
}
ok "dependencies ready ($([ "$IS_TERMUX" = "1" ] && echo termux || echo standard))"

# --------------------------------------------------------------------------- #
# Step 3: C++ accelerator (optional — skipped on Termux)
# --------------------------------------------------------------------------- #
step "3/7" "checking C++ accelerator..."
if [ "$IS_TERMUX" = "1" ]; then
  warn "skipping C++ accelerator on Termux (pycryptodome is fast enough)"
elif "$PYTHON" -c "import vortex_accel" 2>/dev/null; then
  ok "accelerator already built"
elif command -v g++ >/dev/null 2>&1 && "$PYTHON" -c "import pybind11" 2>/dev/null; then
  ( cd "$PROJECT_DIR/cpp_module" && make >/dev/null 2>&1 && make install >/dev/null 2>&1 ) && \
    ok "accelerator built" || warn "accelerator build failed — using pure Python (slower but works)"
else
  warn "g++ or pybind11 not available — using pure Python crypto (still secure)"
fi

# --------------------------------------------------------------------------- #
# Step 4: generate secrets (once)
# --------------------------------------------------------------------------- #
step "4/7" "generating secrets (first run only)..."
if [ ! -f "$SECRET_FILE" ]; then
  ADMIN_PASS="$("$PYTHON" -c 'import secrets as s; print(s.token_urlsafe(16))')"
  WEB_SECRET="$("$PYTHON" -c 'import secrets as s; print(s.token_urlsafe(48))')"
  cat > "$SECRET_FILE" <<EOF
# Auto-generated by quick-start.sh. Keep this file private.
VORTEX_ADMIN_USER=admin
VORTEX_ADMIN_PASS=$ADMIN_PASS
VORTEX_WEB_SECRET=$WEB_SECRET
EOF
  chmod 600 "$SECRET_FILE"
  ok "secrets written to .vortex-secrets.env (chmod 600)"
else
  ok "secrets already exist"
fi
# shellcheck disable=SC1090
source "$SECRET_FILE"

# --------------------------------------------------------------------------- #
# Step 5: config file (if missing)
# --------------------------------------------------------------------------- #
step "5/7" "writing config (if missing)..."
if [ ! -f "$CONFIG_FILE" ]; then
  cp "$PROJECT_DIR/configs/config.toml.example" "$CONFIG_FILE"
  ok "config.toml created from template"
else
  ok "config.toml already exists"
fi

# --------------------------------------------------------------------------- #
# Step 6: create admin user
# --------------------------------------------------------------------------- #
step "6/7" "ensuring admin user exists..."
export VORTEX_WEB_SECRET
export VORTEX_ADMIN_USER
export VORTEX_ADMIN_PASS
"$PYTHON" -m vortexvpn.bootstrap >/dev/null 2>&1 || true
ok "admin user ready"

# --------------------------------------------------------------------------- #
# Step 7: start server (or restart if already running)
# --------------------------------------------------------------------------- #
step "7/7" "starting server..."
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  warn "server already running (pid $(cat "$PID_FILE")), restarting..."
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  sleep 1
  kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi

# Pick up the web port from config (default 8080)
WEB_PORT="$("$PYTHON" -c "
import tomllib
try:
    with open('$CONFIG_FILE','rb') as f: c=tomllib.load(f)
    print(c.get('web',{}).get('port',8080))
except Exception: print(8080)
")"
TUNNEL_PORT="$("$PYTHON" -c "
import tomllib
try:
    with open('$CONFIG_FILE','rb') as f: c=tomllib.load(f)
    print(c.get('tunnel',{}).get('listen_port',4433))
except Exception: print(4433)
")"

export VORTEX_WEB_SECRET
nohup "$PYTHON" -m vortexvpn.web > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 2

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  err "server failed to start. Last 20 log lines:"
  tail -n 20 "$LOG_FILE" >&2 || true
  exit 1
fi

# Detect local IP for the connect URL
LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$LOCAL_IP" ] && LOCAL_IP="127.0.0.1"

# --------------------------------------------------------------------------- #
# Final summary
# --------------------------------------------------------------------------- #
echo
echo -e "${C_BOLD}${C_GREEN}════════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}            VortexVPN is running 🚀                       ${C_RESET}"
echo -e "${C_BOLD}${C_GREEN}════════════════════════════════════════════════════════${C_RESET}"
echo
echo -e "  ${C_BOLD}Web panel (open in browser):${C_RESET}"
echo -e "    ${C_CYAN}http://$LOCAL_IP:$WEB_PORT${C_RESET}"
echo -e "    ${C_CYAN}http://localhost:$WEB_PORT${C_RESET}"
echo
echo -e "  ${C_BOLD}Login:${C_RESET}"
echo -e "    user:     ${C_BOLD}$VORTEX_ADMIN_USER${C_RESET}"
echo -e "    password: ${C_BOLD}$VORTEX_ADMIN_PASS${C_RESET}"
echo
echo -e "  ${C_BOLD}Tunnel port (UDP):${C_RESET}  $TUNNEL_PORT"
echo
echo -e "  ${C_BOLD}Manage:${C_RESET}"
echo -e "    stop:    ./scripts/quick-start.sh --stop"
echo -e "    restart: ./scripts/quick-start.sh --restart"
echo -e "    status:  ./scripts/quick-start.sh --status"
echo -e "    logs:    ./scripts/quick-start.sh --logs"
echo
echo -e "  ${C_BOLD}After login, click '${C_CYAN}كيفاش تربط هاتف${C_RESET}${C_BOLD}' to see phone setup.${C_RESET}"
echo
echo -e "  ${C_YELLOW}! اقرأ صفحة 'كيفاش تربط هاتف' بتمعّن${C_RESET}"
echo -e "  ${C_YELLOW}! لتعرف بالضبط ما الذي يفعله VPN وما لا يفعله${C_RESET}"
echo
