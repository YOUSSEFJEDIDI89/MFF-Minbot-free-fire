#!/usr/bin/env bash
# Build & run the Java monitor.
#
# Build:  ./run.sh build
# Run:    ./run.sh start [port] [interval_ms]
# Stop:   ./run.sh stop
# Logs:   ./run.sh logs

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
CLASS_DIR="$HERE/build"
PID_FILE="$HERE/vortex-monitor.pid"
LOG_FILE="$HERE/vortex-monitor.log"

mkdir -p "$CLASS_DIR"

case "${1:-start}" in
  build)
    echo "[build] compiling VortexMonitor.java"
    javac -d "$CLASS_DIR" "$HERE/VortexMonitor.java"
    echo "[build] OK -> $CLASS_DIR/VortexMonitor.class"
    ;;
  start)
    if [ ! -f "$CLASS_DIR/VortexMonitor.class" ]; then
      "$0" build
    fi
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "already running, pid $(cat "$PID_FILE")"; exit 0
    fi
    PORT="${2:-9101}"
    INTERVAL="${3:-1000}"
    nohup java -Dvortex.monitor.port="$PORT" -cp "$CLASS_DIR" VortexMonitor \
      "/var/run/vortexvpn/monitor.sock" "$INTERVAL" 3600 \
      > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "[start] monitor pid $(cat "$PID_FILE") on port $PORT (interval ${INTERVAL}ms)"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      PID="$(cat "$PID_FILE")"
      kill "$PID" 2>/dev/null && echo "[stop] sent SIGTERM to $PID" || echo "not running"
      rm -f "$PID_FILE"
    else
      echo "not running"
    fi
    ;;
  logs)
    tail -f "$LOG_FILE"
    ;;
  *)
    echo "usage: $0 {build|start [port] [interval_ms]|stop|logs}" >&2
    exit 1
    ;;
esac
