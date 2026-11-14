#!/bin/bash
# The database had no backup. Run nightly by launchd
# (ops/com.golaiet.backup.plist): pg_dump through the db container into a
# folder outside the repo, 30 days kept. The dump is written beside its
# final name and moved, so a dump that failed halfway never looks whole.
# Restoring one is in the README.
set -eu

BACKUP_DIR="${BACKUP_DIR:-$HOME/Backups/golaiet}"
KEEP_DAYS="${KEEP_DAYS:-30}"
CONTAINER="${CONTAINER:-golaiet-db}"
LOG_DIR="${LOG_DIR:-$(cd "$(dirname "$0")/.." && pwd)/logs}"

mkdir -p "$BACKUP_DIR" "$LOG_DIR"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
target="$BACKUP_DIR/golaiet-$(date +%Y-%m-%d).dump"
# A run that was killed mid-dump (the Mac shut down) leaves its half file behind; no later run owns it.
rm -f "$BACKUP_DIR"/golaiet-*.dump.partial

if docker exec "$CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$target.partial"; then
    mv "$target.partial" "$target"
    echo "$now ok $(wc -c < "$target" | tr -d ' ') bytes $target" >> "$LOG_DIR/backup.log"
    # The dump is safe by now; failing to drop old ones is its own line, not a silent end of the run.
    find "$BACKUP_DIR" -name 'golaiet-*.dump' -mtime "+$KEEP_DAYS" -delete \
        || echo "$now could not remove dumps older than $KEEP_DAYS days" >> "$LOG_DIR/backup.log"
else
    rm -f "$target.partial"
    echo "$now failed" >> "$LOG_DIR/backup.log"
    osascript -e 'display notification "The nightly database dump failed" with title "Golaiet" sound name "Basso"'
    exit 1
fi
