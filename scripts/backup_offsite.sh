#!/bin/sh
#
# Copies local backups to an OFFSITE S3-compatible target.
#
# Without this, `db_backup` and `files_backup` both write into a docker volume
# on the same machine as the database. That is a copy, not a backup: if the
# host dies, is stolen, or its disk fails, the database and every backup of it
# die together. Ransomware encrypts both in one pass.
#
# OFFSITE MEANS A DIFFERENT FAILURE DOMAIN. Pointing this at the MinIO
# container running beside Postgres satisfies the script and none of the point
# — use a different provider, or at minimum a different machine and region:
#
#   AWS S3, Cloudflare R2, Backblaze B2, DigitalOcean Spaces, or a MinIO on
#   separate hardware.
#
# Required env:
#   OFFSITE_ENDPOINT_URL   e.g. https://s3.eu-west-1.amazonaws.com
#                          (empty for AWS with a region-derived endpoint)
#   OFFSITE_ACCESS_KEY
#   OFFSITE_SECRET_KEY
#   OFFSITE_BUCKET
# Optional:
#   BACKUP_DIR             (default /backups — what db_backup/files_backup write)
#   OFFSITE_PREFIX         (default helpdoctor)
#
# The credentials should be WRITE-ONLY where the provider supports it (S3:
# s3:PutObject without s3:DeleteObject). A host that can delete its own offsite
# backups has not moved the failure domain very far — that is precisely what
# ransomware does once it owns the machine.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
OFFSITE_PREFIX="${OFFSITE_PREFIX:-helpdoctor}"

: "${OFFSITE_ACCESS_KEY:?OFFSITE_ACCESS_KEY is required}"
: "${OFFSITE_SECRET_KEY:?OFFSITE_SECRET_KEY is required}"
: "${OFFSITE_BUCKET:?OFFSITE_BUCKET is required}"

echo "[$(date -u)] Starting offsite sync of ${BACKUP_DIR} -> ${OFFSITE_BUCKET}/${OFFSITE_PREFIX}"

mc alias set offsite \
    "${OFFSITE_ENDPOINT_URL:-https://s3.amazonaws.com}" \
    "$OFFSITE_ACCESS_KEY" "$OFFSITE_SECRET_KEY" >/dev/null

# mirror, NOT `mirror --remove`. The local side rotates on its own schedule, and
# propagating those deletions would let a local rotation bug — or an attacker
# with the host — erase the offsite history too. Offsite retention belongs to
# the provider's lifecycle policy, where this machine cannot reach it.
mc mirror --quiet --overwrite "$BACKUP_DIR" "offsite/${OFFSITE_BUCKET}/${OFFSITE_PREFIX}"

# Verify by reading BACK from the remote rather than trusting the exit code.
# A sync that "succeeded" while writing nothing is the failure mode that hides
# for months and is discovered on the day it is needed.
remote_count="$(mc ls --recursive "offsite/${OFFSITE_BUCKET}/${OFFSITE_PREFIX}" | wc -l)"

if [ "$remote_count" -eq 0 ]; then
    echo "[$(date -u)] ERROR: offsite target holds 0 objects after sync" >&2
    exit 1
fi

echo "[$(date -u)] Offsite sync complete (${remote_count} objects at destination)"
