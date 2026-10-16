#!/bin/bash
# #12 (spec 2026-10-15): manual/off-schedule pg_dump — cùng hợp đồng với
# scheduler job backup-db (server/app/core/db.py::backup_database).
# Usage: backup.sh [--retention 14] [--output-dir /backups]
set -euo pipefail

RETENTION=14
OUTPUT_DIR=/backups

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') [backup] $*"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --retention)
            RETENTION="${2:?--retention cần số ngày}"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="${2:?--output-dir cần đường dẫn}"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--retention DAYS] [--output-dir DIR]"
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if ! [[ "$RETENTION" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --retention phải là số nguyên (nhận: $RETENTION)" >&2
    exit 2
fi

: "${DATABASE_URL:?DATABASE_URL is required}"

# libpq không hiểu scheme postgresql+asyncpg:// (asyncpg-only) → strip.
PG_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"

mkdir -p "$OUTPUT_DIR"
DEST="$OUTPUT_DIR/img2text-$(date -u +%Y%m%d-%H%M%S).sql.gz"

log "pg_dump → $DEST"
if ! pg_dump "$PG_URL" | gzip > "$DEST"; then
    rm -f "$DEST"
    log "ERROR: pg_dump failed — partial dump removed"
    exit 1
fi

if [[ "$RETENTION" -gt 0 ]]; then
    mapfile -t stale < <(find "$OUTPUT_DIR" -maxdepth 1 -name 'img2text-*.sql.gz' -mtime +"$RETENTION")
    if ((${#stale[@]})); then
        rm -f -- "${stale[@]}"
        log "pruned ${#stale[@]} backup(s) older than ${RETENTION}d"
    fi
fi

log "ok: $DEST ($(stat -c%s "$DEST") bytes)"
