#!/bin/bash
# The watcher outside the stack: nothing inside compose can report that
# compose is down (the Mac rebooted on 2026-11-02 and no job ran for three
# days, unnoticed). Run hourly by launchd (ops/com.golaiet.watch.plist).
# Reads /api/health, appends one line to logs/watch.log and shows a macOS
# notification when the stack does not answer or the heartbeat is too old.
set -u

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8003/api/health}"
MAX_AGE_MINUTES="${MAX_AGE_MINUTES:-90}"
LOG_DIR="${LOG_DIR:-$(cd "$(dirname "$0")/.." && pwd)/logs}"
# test_ seam: tests/test_ops.py replaces the notification with a command it can read.
test_notify="${test_notify:-}"

notify() {
    if [ -n "$test_notify" ]; then
        $test_notify "$1"
    else
        osascript -e "display notification \"$1\" with title \"Golaiet\" sound name \"Basso\""
    fi
}

mkdir -p "$LOG_DIR"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if ! body="$(curl -fsS -m 20 "$HEALTH_URL" 2>/dev/null)"; then
    echo "$now unreachable" >> "$LOG_DIR/watch.log"
    notify "The stack does not answer at $HEALTH_URL"
    exit 0
fi

heartbeat="$(printf '%s' "$body" | sed -n 's/.*"last_heartbeat": *"\([^"]*\)".*/\1/p')"
if [ -z "$heartbeat" ]; then
    echo "$now no-heartbeat" >> "$LOG_DIR/watch.log"
    notify "The stack answers but has never recorded a heartbeat"
    exit 0
fi

# 2026-11-09T05:33:36.837Z → epoch seconds (BSD date; the fraction is dropped).
heartbeat_epoch="$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "${heartbeat%%.*}" +%s 2>/dev/null)"
if [ -z "$heartbeat_epoch" ]; then
    echo "$now unreadable heartbeat=$heartbeat" >> "$LOG_DIR/watch.log"
    notify "The health endpoint returned a heartbeat time that could not be read"
    exit 0
fi
age_minutes=$(( ( $(date -u +%s) - heartbeat_epoch ) / 60 ))

if [ "$age_minutes" -gt "$MAX_AGE_MINUTES" ]; then
    echo "$now stale age_minutes=$age_minutes" >> "$LOG_DIR/watch.log"
    notify "The scheduler's last heartbeat is $age_minutes minutes old"
else
    echo "$now ok age_minutes=$age_minutes" >> "$LOG_DIR/watch.log"
fi
