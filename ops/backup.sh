#!/bin/bash
# The database had no backup. Run nightly by launchd
# (ops/com.golaiet.backup.plist): pg_dump through the db container into a
# folder outside the repo, 30 days kept. The dump is written beside its
# final name and moved, so a dump that failed halfway never looks whole.
# Restore: docker exec -i golaiet-db pg_restore -U <user> -d <scratch db> < file
set -eu

BACKUP_DIR="${BACKUP_DIR:-$HOME/Backups/golaiet}"
KEEP_DAYS="${KEEP_DAYS:-30}"
CONTAINER="${CONTAINER:-golaiet-db}"
LOG_DIR="${LOG_DIR:-$(cd "$(dirname "$0")/.." && pwd)/logs}"

mkdir -p "$BACKUP_DIR" "$LOG_DIR"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
target="$BACKUP_DIR/golaiet-$(date +%Y-%m-%d).dump"

if docker exec "$CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$target.partial"; then
    mv "$target.partial" "$target"
    find "$BACKUP_DIR" -name 'golaiet-*.dump' -mtime "+$KEEP_DAYS" -delete
    echo "$now ok $(wc -c < "$target" | tr -d ' ') bytes $target" >> "$LOG_DIR/backup.log"
else
    rm -f "$target.partial"
    echo "$now failed" >> "$LOG_DIR/backup.log"
    osascript -e 'display notification "The nightly database dump failed" with title "Golaiet" sound name "Basso"'
    exit 1
fi
