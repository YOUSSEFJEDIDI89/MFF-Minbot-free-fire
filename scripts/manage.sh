#!/usr/bin/env bash
# manage.sh - start/stop/status/restart the VortexVPN server.
#
# Usage:
#   ./manage.sh start     # launch web panel + tunnel in background
#   ./manage.sh stop
#   ./manage.sh restart
#   ./manage.sh status
#   ./manage.sh logs [n]

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${VORTEX_HOME:-$(dirname "$HERE")}"
VENV_DIR="$INSTALL_DIR/venv"
PID_FILE="/var/run/vortexvpn/vortexvpn.pid"
LOG_FILE="/var/log/vortexvpn/vortexvpn.log"

PYTHON="$VENV_DIR/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

mkdir -p /var/run/vortexvpn /var/log/vortexvpn

is_running() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-status}" in
    start)
        if is_running; then
            echo "already running, pid $(cat "$PID_FILE")"
            exit 0
        fi
        echo "[+] starting VortexVPN..."
        nohup "$PYTHON" -m vortexvpn.web \
            > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 1
        if is_running; then
            echo "[+] started, pid $(cat "$PID_FILE"). logs -> $LOG_FILE"
        else
            echo "[!] failed to start, check $LOG_FILE" >&2
            exit 1
        fi
        ;;
    stop)
        if is_running; then
            PID="$(cat "$PID_FILE")"
            echo "[+] stopping pid $PID"
            kill "$PID" 2>/dev/null || true
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                kill -0 "$PID" 2>/dev/null || break
                sleep 0.5
            done
            kill -9 "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
        else
            echo "not running"
        fi
        ;;
    restart)
        "$0" stop || true
        "$0" start
        ;;
    status)
        if is_running; then
            echo "running, pid $(cat "$PID_FILE")"
            exit 0
        else
            echo "stopped"
            exit 3
        fi
        ;;
    logs)
        tail -n "${2:-100}" -f "$LOG_FILE"
        ;;
    *)
        echo "usage: $0 {start|stop|restart|status|logs [n]}" >&2
        exit 1
        ;;
esac
