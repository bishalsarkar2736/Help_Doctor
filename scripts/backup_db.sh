#!/usr/bin/env bash
#
# Automated PostgreSQL backup with rotation.
#
# Produces a compressed pg_dump into $BACKUP_DIR and deletes dumps older
# than $RETENTION_DAYS. Designed to be run from cron, e.g. hourly:
#
#   0 * * * * /app/scripts/backup_db.sh >> /var/log/helpdoctor_backup.log 2>&1
#
# Required env (falls back to the app's POSTGRES_* vars):
#   POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
# Optional:
#   BACKUP_DIR       (default: ./backups)
#   RETENTION_DAYS   (default: 7)
#
# NOTE: restore with:
#   gunzip -c <file>.sql.gz | psql "postgresql://user:pass@host:port/db"
#
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
outfile="${BACKUP_DIR}/${POSTGRES_DB}_${timestamp}.sql.gz"

echo "[$(date -u)] Starting backup of ${POSTGRES_DB} -> ${outfile}"

# pg_dump reads the password from PGPASSWORD; never put it on the command line.
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    --host="$POSTGRES_HOST" \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --no-owner \
    --format=plain \
    | gzip > "$outfile"

# Fail loudly if the dump is suspiciously small (e.g. auth failed mid-pipe).
min_bytes=1024
actual_bytes="$(stat -c%s "$outfile")"
if [ "$actual_bytes" -lt "$min_bytes" ]; then
    echo "[$(date -u)] ERROR: backup file is only ${actual_bytes} bytes - treating as failure" >&2
    rm -f "$outfile"
    exit 1
fi

echo "[$(date -u)] Backup complete (${actual_bytes} bytes)"

# Rotate: delete dumps older than the retention window.
deleted="$(find "$BACKUP_DIR" -name "${POSTGRES_DB}_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)"
echo "[$(date -u)] Rotation removed ${deleted} backup(s) older than ${RETENTION_DAYS} days"
