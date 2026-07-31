#!/bin/sh
#
# Backs up the object storage bucket — doctor credential documents, clinic
# logos and doctor signatures.
#
# db_backup covers Postgres only. A database restore returns the
# doctor_documents row and the storage key it points at, but NOT the file
# itself, so without this a restore leaves every BMDC certificate and medical
# licence unrecoverable. Those are legal documents collected from
# practitioners; re-collecting them is not a realistic recovery plan.
#
# Runs in the minio/mc image, which has no tar, so this mirrors into a dated
# directory rather than producing an archive. That is arguably better anyway:
# restores can pull a single file without unpacking, and mc mirror only
# transfers what changed.
#
# The minio/mc image is minimal: it has wc, ls, sort, head, date, rm, mkdir and
# expr, but NOT find, awk, sed or grep. Everything below sticks to that set.
# Reaching for `find` here already cost one good backup: the count check failed
# with "find: command not found", read as 0 objects, and deleted a snapshot
# that had mirrored correctly.
#
# Required env:
#   S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET
# Optional:
#   BACKUP_DIR            (default /backups/objects)
#   RETENTION_SNAPSHOTS   (default 28 — with the 6-hourly interval, ~7 days)
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups/objects}"
# Count-based, not age-based: date arithmetic needs tools this image lacks, and
# snapshot directory names sort chronologically, so "keep the newest N" is both
# simpler and harder to get wrong.
RETENTION_SNAPSHOTS="${RETENTION_SNAPSHOTS:-28}"

: "${S3_ENDPOINT_URL:?S3_ENDPOINT_URL is required}"
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
: "${S3_BUCKET:?S3_BUCKET is required}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${BACKUP_DIR}/${timestamp}"

echo "[$(date -u)] Starting object backup of ${S3_BUCKET} -> ${target}"

mc alias set hdbackup "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null

# Remove a partial directory if the mirror fails, so a half-copied snapshot is
# never mistaken for a complete one. Same failure mode the database script hit.
cleanup_partial() {
    status=$?
    if [ "$status" -ne 0 ] && [ -d "$target" ]; then
        echo "[$(date -u)] Removing partial backup ${target}" >&2
        rm -rf "$target"
    fi
    exit "$status"
}
trap cleanup_partial EXIT

mkdir -p "$target"
mc mirror --quiet --overwrite "hdbackup/${S3_BUCKET}" "$target"

# An empty snapshot is a failure, not a success: the bucket always holds at
# least the signatures directory once the app has run. Silently keeping empty
# snapshots is how a broken backup survives unnoticed for weeks.
#
# mc lists local paths as well as remote ones, which is how this counts files
# without `find`.
count="$(mc ls --recursive "$target" | wc -l)"
if [ "$count" -eq 0 ]; then
    echo "[$(date -u)] ERROR: mirrored 0 objects - treating as failure" >&2
    exit 1
fi

echo "[$(date -u)] Object backup complete (${count} objects)"

# Rotate: keep the newest RETENTION_SNAPSHOTS directories. Names are
# YYYYMMDDTHHMMSSZ, so lexical order is chronological order.
total="$(ls -1 "$BACKUP_DIR" | wc -l)"
removed=0

if [ "$total" -gt "$RETENTION_SNAPSHOTS" ]; then
    drop="$(expr "$total" - "$RETENTION_SNAPSHOTS")"
    for old in $(ls -1 "$BACKUP_DIR" | sort | head -n "$drop"); do
        rm -rf "${BACKUP_DIR}/${old}"
        removed="$(expr "$removed" + 1)"
    done
fi

echo "[$(date -u)] Rotation removed ${removed} snapshot(s), keeping newest ${RETENTION_SNAPSHOTS}"
