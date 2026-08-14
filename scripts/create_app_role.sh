#!/usr/bin/env bash
#
# Create (or update) the least-privilege runtime role, using the privileged
# credential. Idempotent — run it on every deploy, and after any migration that
# predates the default privileges.
#
#   APP_DB_PASSWORD=... scripts/create_app_role.sh
#
# Connects with POSTGRES_* from the environment, which describe the OWNER. The
# restricted role's password comes from APP_DB_PASSWORD and is passed as a psql
# variable rather than interpolated into the SQL file, so it never appears in a
# file on disk or in the repository.

set -euo pipefail

: "${APP_DB_PASSWORD:?set APP_DB_PASSWORD to the password for helpdoctor_app}"
: "${POSTGRES_DB:?}"
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"

HOST="${POSTGRES_HOST:-localhost}"
PORT="${POSTGRES_PORT:-5432}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# PGPASSWORD rather than a URL: the password stays out of the process title,
# which `ps` shows to every user on the box.
PGPASSWORD="$POSTGRES_PASSWORD" psql \
    --host "$HOST" \
    --port "$PORT" \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --no-psqlrc \
    --quiet \
    -v ON_ERROR_STOP=1 \
    -v "app_password=$APP_DB_PASSWORD" \
    -v "db=$POSTGRES_DB" \
    -f "$here/create_app_role.sql"

echo "helpdoctor_app is present with least-privilege grants on $POSTGRES_DB"
