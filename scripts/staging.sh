#!/usr/bin/env bash
#
# Staging environment: a second, isolated instance of the stack for validating
# deployment and operations before promoting a change to production.
#
#   scripts/staging.sh up       build, start, migrate, wait for health, verify
#   scripts/staging.sh migrate  apply pending migrations to a RUNNING staging
#   scripts/staging.sh check    verify the schema is at head and free of drift
#   scripts/staging.sh seed    bootstrap super admin + clinic + test accounts
#   scripts/staging.sh smoke   run the operational checks against it
#   scripts/staging.sh status  what is running
#   scripts/staging.sh logs    follow logs
#   scripts/staging.sh down    stop and DELETE staging volumes
#
# Runs alongside production without touching it: its own compose project (so
# its own network and volumes), its own container names, its own host ports,
# and its own generated secrets.
#
# SECRETS ARE GENERATED, NEVER COPIED FROM PRODUCTION. A staging environment is
# by definition the less guarded one — it gets test data, wider access and more
# experimentation — so sharing a JWT signing key or a database password with
# production would mean a staging compromise is a production compromise.
set -euo pipefail

cd "$(dirname "$0")/.."

PROJECT=helpdoctor_staging
FILES=(-f docker-compose.yml -f docker-compose.staging.yml)
ENV_FILE=.env.staging

# The application services. The observability stack and backup loops are left
# out on purpose: they double the container count on a single machine and add
# little to deployment validation.
SERVICES=(postgres redis minio minio_init mailhog migrate api celery_worker celery_beat outbox_worker web)

API_URL=http://127.0.0.1:18000
WEB_URL=http://127.0.0.1:15173

compose() {
    docker compose -p "$PROJECT" "${FILES[@]}" "$@"
}

generate_env() {
    if [ -f "$ENV_FILE" ]; then
        echo "==> $ENV_FILE exists, keeping it"
        return
    fi

    echo "==> generating $ENV_FILE with fresh secrets"

    local pg jwt minio_secret
    pg=$(python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(28)))")
    jwt=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
    minio_secret=$(python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(28)))")

    # Start from the committed example, exactly as a new deployer would, then
    # point it at the staging service names. Anything missing from
    # .env.example will fail here, which is the point: staging is where a
    # broken example gets caught rather than in production.
    sed -e "s|^ENV=.*|ENV=staging|" \
        -e "s|^POSTGRES_HOST=.*|POSTGRES_HOST=postgres|" \
        -e "s|^POSTGRES_PORT=.*|POSTGRES_PORT=5432|" \
        -e "s|^POSTGRES_DB=.*|POSTGRES_DB=helpdoctor_db|" \
        -e "s|^POSTGRES_USER=.*|POSTGRES_USER=helpdoctor_user|" \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pg|" \
        -e "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$jwt|" \
        -e "s|^REDIS_URL=.*|REDIS_URL=redis://redis:6379/0|" \
        -e "s|^REDIS_HOST=.*|REDIS_HOST=redis|" \
        -e "s|^RATE_LIMIT_STORAGE_URI=.*|RATE_LIMIT_STORAGE_URI=redis://redis:6379/1|" \
        -e "s|^MAIL_HOST=.*|MAIL_HOST=mailhog|" \
        -e "s|^MAIL_PORT=.*|MAIL_PORT=1025|" \
        -e "s|^STORAGE_BACKEND=.*|STORAGE_BACKEND=s3|" \
        -e "s|^S3_ENDPOINT_URL=.*|S3_ENDPOINT_URL=http://minio:9000|" \
        -e "s|^S3_ACCESS_KEY=.*|S3_ACCESS_KEY=staging|" \
        -e "s|^S3_SECRET_KEY=.*|S3_SECRET_KEY=$minio_secret|" \
        .env.example > "$ENV_FILE"

    # Compose interpolates ${POSTGRES_*} and ${S3_*} for the postgres and minio
    # services from the project directory's .env, which is production's. Pass
    # staging's values through the environment instead so the two never mix.
    echo "==> $ENV_FILE written ($(grep -c = "$ENV_FILE") keys)"
}

load_staging_env() {
    # Export every staging value into the environment before compose runs.
    #
    # Compose needs these for two different purposes and both must agree:
    # ${POSTGRES_PASSWORD} interpolation in the base file, and env_file for the
    # containers themselves. Passing them as a prefix assignment in front of a
    # wrapper function was too subtle to trust — postgres came up initialised
    # with the PRODUCTION password while every app container used the staging
    # one, so the stack was healthy and every connection was refused.
    #
    # Sourcing is explicit: one mechanism, visible in `env`, and easy to check.
    set -a
    # shellcheck disable=SC1090
    . "./$ENV_FILE"
    set +a
}

verify_schema() {
    # ONE implementation, shared with production.
    #
    # This used to inline the whole check here in shell. It now lives in
    # scripts/verify_schema.py and runs inside the image, which is also what the
    # `migrate` service itself runs after upgrading:
    #
    #     command: sh -c 'alembic upgrade head && python -m scripts.verify_schema'
    #
    # So `staging.sh up` is already gated by compose before this line is
    # reached. This call is for the OTHER case -- checking a stack that is
    # already running, where nothing has re-run the migrate service -- and for
    # `staging.sh check`.
    echo "==> verifying the staging schema"

    if ! compose run --rm --entrypoint sh migrate -c 'python -m scripts.verify_schema'; then
        echo "!!! staging schema verification FAILED" >&2
        echo "!!! run: scripts/staging.sh migrate" >&2
        exit 1
    fi
}

wait_for_health() {
    echo "==> waiting for the api to report ready"
    local n=0
    until [ "$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/health/ready" 2>/dev/null)" = "200" ]; do
        n=$((n + 1))
        if [ "$n" -gt 60 ]; then
            echo "!!! api never became ready; last 40 log lines:" >&2
            compose logs --tail 40 api >&2 || true
            exit 1
        fi
        sleep 3
    done
    echo "==> api ready"
}

case "${1:-}" in
    up)
        generate_env
        load_staging_env
        echo "==> building"
        compose build "${SERVICES[@]}"
        echo "==> starting"
        compose up -d "${SERVICES[@]}"
        wait_for_health
        verify_schema
        echo
        echo "  api : $API_URL"
        echo "  web : $WEB_URL"
        echo "  run: scripts/staging.sh smoke"
        ;;

    migrate)
        # The gap that let staging drift. `migrate` is a one-shot service, so it
        # only re-runs when the stack is brought up; a stack that simply keeps
        # running never applies anything new. This applies pending migrations to
        # a RUNNING staging without recreating it.
        #
        # Safe to run at any time: alembic upgrade head does nothing,
        # successfully, when there is nothing to do.
        load_staging_env
        echo "==> applying migrations"
        compose run --rm migrate
        verify_schema
        echo "==> staging schema is current"
        ;;

    check)
        # Verification on its own, for a cron or a pre-promotion gate.
        load_staging_env
        verify_schema
        echo "==> staging schema is current"
        ;;

    seed)
        load_staging_env

        # Everything below runs against the STAGING postgres port with staging
        # credentials, and follows the real day-one bootstrap path rather than
        # inserting rows directly. That path — create the platform super admin,
        # have it create the first clinic through the API — is what a brand new
        # production deployment has to do, and staging is the only place it
        # gets exercised before someone does it for real.
        export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=15433 PYTHONPATH=.

        echo "==> bootstrapping the platform super admin"
        SUPER_ADMIN_EMAIL="${SUPER_ADMIN_EMAIL:-staging.owner@example.com}" \
        SUPER_ADMIN_PASSWORD="${SUPER_ADMIN_PASSWORD:-Staging-Owner-9417-Pass}" \
        SUPER_ADMIN_NAME="${SUPER_ADMIN_NAME:-Staging Owner}" \
            python3 -m scripts.create_super_admin

        echo "==> creating the first clinic through the API"
        python3 scripts/staging_bootstrap_clinic.py

        echo "==> seeding role accounts"
        python3 scripts/seed_e2e_accounts.py .staging-accounts.json
        echo "==> wrote .staging-accounts.json"
        ;;

    smoke)
        # Feed the smoke test a real account when one has been seeded, so the
        # authentication checks run rather than skipping. They are the ones
        # that exercise the full browser path: proxy, cookie flags, RBAC.
        if [ -f .staging-accounts.json ]; then
            STAGING_SMOKE_EMAIL=$(python3 -c "import json;print(json.load(open('.staging-accounts.json'))['accounts']['admin']['email'])")
            STAGING_SMOKE_PASSWORD=$(python3 -c "import json;print(json.load(open('.staging-accounts.json'))['accounts']['admin']['password'])")
            export STAGING_SMOKE_EMAIL STAGING_SMOKE_PASSWORD
        fi

        PYTHONPATH=. STAGING_API_URL="$API_URL" STAGING_WEB_URL="$WEB_URL" \
            python3 scripts/staging_smoke.py
        ;;

    status)
        load_staging_env
        compose ps
        ;;

    logs)
        load_staging_env
        shift || true
        compose logs -f "$@"
        ;;

    down)
        load_staging_env
        # -v because staging data is disposable by definition, and a stale
        # database is the fastest way to make the next validation lie.
        compose down -v --remove-orphans
        echo "==> staging removed (volumes deleted)"
        ;;

    *)
        echo "usage: scripts/staging.sh {up|migrate|check|seed|smoke|status|logs|down}" >&2
        exit 2
        ;;
esac
