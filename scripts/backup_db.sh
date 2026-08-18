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

# Remove a partial file if anything below fails.
#
# The size guard further down is unreachable when pg_dump itself fails: with
# `set -euo pipefail` the failing pipeline exits the script immediately, so the
# check never runs and a 0-byte gzip is left behind looking like a backup. That
# is exactly what happened when postgres was briefly down during a restart —
# the log correctly said "backup failed" while a plausible-looking file sat in
# the directory for anyone grabbing "the latest" during an incident.
cleanup_partial() {
    status=$?
    if [ "$status" -ne 0 ] && [ -f "$outfile" ]; then
        echo "[$(date -u)] Removing partial backup ${outfile}" >&2
        rm -f "$outfile"
    fi
    exit "$status"
}
trap cleanup_partial EXIT

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

# Report success to Prometheus, AFTER the size guard above.
#
# Placement is the whole point: pushing before that check would publish a fresh
# timestamp for a dump that was then deleted as too small, and the alert would
# stay silent while backups were failing. Nothing below this line may push
# either — a rotation failure must not look like a successful backup.
#
# Written with bash's /dev/tcp because this runs in the postgres image, which
# ships no curl, wget, nc or python. Adding one would mean a custom image for
# the backup service; a redirection that bash already has costs nothing.
#
# NEVER fatal. `set -e` is on and a backup that ran is a backup that ran: a
# pushgateway that is down, renamed or removed must not turn a good dump into a
# failure. It degrades to a log line, and BackupMetricMissing catches the case
# where that keeps happening.
push_success_metric() {
    local host="${PUSHGATEWAY_HOST:-}"
    local port="${PUSHGATEWAY_PORT:-9091}"

    [ -n "$host" ] || return 0

    local now
    now="$(date -u +%s)"

    # Built with a literal trailing newline rather than $(printf ...\n): command
    # substitution strips trailing newlines, and the Prometheus text format
    # requires the body to end with one. Without it the pushgateway answers
    # 400 "text format parsing error ... unexpected end of input stream" —
    # which cost a debugging round the first time.
    local body
    body="# TYPE helpdoctor_backup_last_success_timestamp gauge
helpdoctor_backup_last_success_timestamp ${now}
"

    exec 3<>"/dev/tcp/${host}/${port}" || return 1

    printf 'POST /metrics/job/db_backup/database/%s HTTP/1.1\r\n' "$POSTGRES_DB" >&3
    printf 'Host: %s:%s\r\n' "$host" "$port" >&3
    printf 'Content-Type: text/plain\r\n' >&3
    printf 'Content-Length: %s\r\n' "${#body}" >&3
    printf 'Connection: close\r\n\r\n' >&3
    printf '%s' "$body" >&3

    local status
    read -r _ status _ <&3
    exec 3<&-
    exec 3>&-

    case "$status" in
        200|202) return 0 ;;
        *) return 1 ;;
    esac
}

if push_success_metric; then
    echo "[$(date -u)] Pushed backup success timestamp"
else
    echo "[$(date -u)] WARNING: could not push backup metric (backup itself is fine)" >&2
fi

# Rotate: delete dumps older than the retention window.
deleted="$(find "$BACKUP_DIR" -name "${POSTGRES_DB}_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)"
echo "[$(date -u)] Rotation removed ${deleted} backup(s) older than ${RETENTION_DAYS} days"
