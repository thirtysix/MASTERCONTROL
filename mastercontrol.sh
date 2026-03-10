#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$DIR/backend"
VENV="$BACKEND/.venv"
PID_FILE="$DIR/data/mastercontrol.pid"
LOG_FILE="$DIR/logs/mastercontrol.log"
HOST="127.0.0.1"
PORT="8000"
URL="http://${HOST}:${PORT}"

# ── helpers ──────────────────────────────────────────────────────────

ensure_venv() {
    if [ ! -d "$VENV" ]; then
        echo "Creating virtualenv in $VENV ..."
        python3 -m venv "$VENV"
    fi
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
    pip install -q -e "$BACKEND[dev]"
}

is_running() {
    # 1. Check PID file (started via mastercontrol.sh)
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        else
            # Stale PID file — process is dead
            rm -f "$PID_FILE"
        fi
    fi
    # 2. Fallback: check if port is in use (started manually / by another tool)
    if check_port; then
        return 0
    fi
    return 1
}

get_pid() {
    # Return PID from file if valid, otherwise find it from the port
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi
    # Find PID from port listener
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep ":${PORT} " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1
    elif command -v lsof &>/dev/null; then
        lsof -ti :"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1
    fi
}

check_port() {
    # Returns 0 if port is in use
    if command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":${PORT} " && return 0
    elif command -v lsof &>/dev/null; then
        lsof -i :"${PORT}" -sTCP:LISTEN &>/dev/null && return 0
    fi
    return 1
}

wait_for_health() {
    local max_wait=15
    local waited=0
    while [ $waited -lt $max_wait ]; do
        if curl -sf "${URL}/api/system/health" | grep -q '"ok"' 2>/dev/null; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

# ── commands ─────────────────────────────────────────────────────────

do_start() {
    local foreground=false

    for arg in "$@"; do
        case "$arg" in
            --foreground) foreground=true ;;
            --desktop)    ;;  # same as background, used by .desktop file
        esac
    done

    # Already running? Just open the browser.
    if is_running; then
        echo "MASTER CONTROL is already running (PID $(cat "$PID_FILE"))"
        xdg-open "$URL" 2>/dev/null &
        exit 0
    fi

    # Check if something else owns the port
    if check_port; then
        echo "ERROR: Port ${PORT} is already in use by another process."
        echo "  Check with: ss -tlnp | grep :${PORT}"
        exit 1
    fi

    ensure_venv

    # Foreground mode (for development)
    if [ "$foreground" = true ]; then
        echo "Starting MASTER CONTROL (foreground) at ${URL}"
        cd "$BACKEND" && exec uvicorn src.main:app --reload --host "$HOST" --port "$PORT"
    fi

    # Background mode
    mkdir -p "$DIR/data" "$DIR/logs"

    echo "Starting MASTER CONTROL at ${URL}"
    cd "$BACKEND"
    nohup "$VENV/bin/uvicorn" src.main:app \
        --host "$HOST" --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    echo "  PID:  $pid"
    echo "  Log:  $LOG_FILE"

    # Wait for server to be ready, then open browser
    if wait_for_health; then
        echo "  Server is ready."
        xdg-open "$URL" 2>/dev/null &
    else
        echo "  WARNING: Server did not respond within 15s."
        echo "  Check logs: tail -f $LOG_FILE"
    fi
}

do_stop() {
    if ! is_running; then
        echo "MASTER CONTROL is not running."
        exit 0
    fi

    local pid
    pid=$(get_pid)
    if [ -z "$pid" ]; then
        echo "MASTER CONTROL appears to be running but could not determine PID."
        exit 1
    fi
    echo "Stopping MASTER CONTROL (PID $pid)..."

    kill "$pid" 2>/dev/null || true

    # Wait for graceful shutdown (up to 10s)
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [ $waited -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        echo "  Process did not exit gracefully, sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    echo "Stopped."

    if command -v notify-send &>/dev/null; then
        notify-send -i "$DIR/app/static/icon.png" "Master Control" "Server stopped."
    fi
}

do_status() {
    local msg
    if is_running; then
        local pid
        pid=$(get_pid)
        msg="Running (PID ${pid:-unknown})\nURL: $URL\nLog: $LOG_FILE"
    else
        msg="Not running."
    fi

    echo -e "MASTER CONTROL\n$msg"

    # Desktop notification if available (used by .desktop right-click action)
    if command -v notify-send &>/dev/null; then
        notify-send -i "$DIR/app/static/icon.png" "Master Control" "$msg"
    fi
}

# ── main dispatch ────────────────────────────────────────────────────

case "${1:-start}" in
    start)   shift || true; do_start "$@" ;;
    stop)    do_stop ;;
    status)  do_status ;;
    restart) do_stop; sleep 1; shift || true; do_start "$@" ;;
    *)
        echo "Usage: $(basename "$0") {start|stop|status|restart} [--foreground]"
        exit 1
        ;;
esac
