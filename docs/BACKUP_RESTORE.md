# Backup and restore

An untested backup is not a backup. This procedure has been executed end to end
against real data; the results are recorded at the bottom.

## What is backed up

`db_backup` (compose service) runs `scripts/backup_db.sh` every
`BACKUP_INTERVAL_SECONDS` (default hourly), writing a gzipped `pg_dump` of
`helpdoctor_db` into the `db_backups` volume and deleting dumps older than
`RETENTION_DAYS` (default 7).

That covers everything in Postgres — medical records, prescriptions, payments,
`audit_logs`, `phi_access_logs`, users and invitations.

`files_backup` (compose service) covers the **object storage bucket** — doctor
credential documents, clinic logos and signatures — every 6 hours, mirroring
into a dated snapshot under `/backups/objects/` in the same `db_backups`
volume, keeping the newest `RETENTION_SNAPSHOTS` (28 ≈ 7 days).

Both are needed. A database restore alone brings back the `doctor_documents`
row and the storage key it points at, but not the file: without the object
backup, every BMDC certificate and medical licence is unrecoverable, and
re-collecting legal documents from practitioners is not a recovery plan.

### Restoring a single file

Snapshots are plain directories, so a single document can be pulled back
without unpacking anything:

```bash
SNAP=$(docker exec helpdoctor_files_backup sh -c 'ls -1 /backups/objects | tail -1')
KEY=uploads/doctor_documents/doctor1_LICENSE_7c13fc.pdf

# inspect
docker exec helpdoctor_files_backup sh -c "cat /backups/objects/$SNAP/$KEY" > recovered.pdf

# put it back
docker run --rm --network help_doctor_default \
  -e MC_HOST_hd="http://$S3_ACCESS_KEY:$S3_SECRET_KEY@minio:9000" \
  -v "$PWD:/local" minio/mc:latest cp "/local/recovered.pdf" "hd/$S3_BUCKET/$KEY"
```

Verified on 2026-08-01: a credential document restored from a snapshot is
byte-identical (sha256) to the live object.

## Restore drill (safe — never touches live data)

Restore into a throwaway database first. Never restore over `helpdoctor_db` to
"test" it.

```bash
# 1. Take (or pick) a dump
docker exec helpdoctor_db_backup /backup_db.sh
LATEST=$(docker exec helpdoctor_db_backup sh -c 'ls -t /backups/*.sql.gz | head -1')

# 2. Restore into an isolated database
docker exec helpdoctor_postgres psql -U helpdoctor_user -d postgres \
  -c "DROP DATABASE IF EXISTS restore_drill;" \
  -c "CREATE DATABASE restore_drill OWNER helpdoctor_user;"

docker exec helpdoctor_db_backup sh -c "gzip -dc $LATEST" \
  | docker exec -i helpdoctor_postgres psql -U helpdoctor_user -d restore_drill -q

# 3. Verify (see checks below)

# 4. Clean up
docker exec helpdoctor_postgres psql -U helpdoctor_user -d postgres \
  -c "DROP DATABASE restore_drill;"
```

## What to verify — row counts are not enough

Equal row counts prove very little. Check all four:

**1. Content, not counts.** Compare a checksum over real field values:

```sql
SELECT md5(string_agg(x, '|' ORDER BY x)) FROM (
  SELECT id||':'||coalesce(email,'')||':'||role::text FROM users
  UNION ALL SELECT id||':'||coalesce(notes,'')||':'||status::text FROM prescriptions
  UNION ALL SELECT id||':'||medicine_name||':'||coalesce(dosage,'') FROM prescription_items
  UNION ALL SELECT id||':'||event_type||':'||action||':'||coalesce(details::text,'') FROM audit_logs
  UNION ALL SELECT id||':'||resource_type||':'||action||':'||patient_id::text FROM phi_access_logs
  UNION ALL SELECT id||':'||file_path||':'||coalesce(content_type,'') FROM doctor_documents
) t(x);
```

**2. Schema and migration state.** Tables, indexes, FKs, checks, and
`alembic_version` must match — a dump restored at the wrong revision will fail
on the next `alembic upgrade`.

**3. Sequences.** The classic restore failure: data comes back but sequences
reset to 1, and the next insert dies on a duplicate primary key. Compare
`SELECT last_value FROM users_id_seq;`.

**4. The application actually runs against it.** Point an API container at the
restored database and log in — that exercises a read *and* a write:

```bash
# NOTE: strip quotes from .env.docker first. Compose's env_file strips
# surrounding quotes; `docker run --env-file` does NOT, so ALGORITHM="HS256"
# arrives as ["HS256"] and every login fails with
#   JWSError: Algorithm "HS256" not supported
sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)="(.*)"$/\1=\2/' .env.docker > /tmp/restore.env

docker run -d --name hdr_restore_api --network help_doctor_default \
  --env-file /tmp/restore.env \
  -e POSTGRES_DB=restore_drill -e POSTGRES_HOST=postgres \
  -p 18099:8000 help_doctor-api

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:18099/health/ready
docker rm -f hdr_restore_api
```

## Real restore (production incident)

Same as the drill, but restore into a new database and repoint the app rather
than dropping the live one — keep the damaged database until the restore is
verified, because it is the only copy of anything written since the last dump.

```bash
createdb helpdoctor_db_restored     # restore here
# verify with the four checks above
# then repoint POSTGRES_DB and restart the api/worker services
```

## Drill results (2026-07-31)

Backup taken from live data and restored into an isolated database:

| check | result |
|---|---|
| all 17 populated tables, row counts | match |
| content checksum (medical, audit, documents) | **identical** |
| schema: 36 tables, 166 indexes, 55 FKs, 6 checks | match |
| `alembic_version` | `b7c4a91e5d38` both |
| `users_id_seq` | 175 both |
| app boots against restored DB | `/health/ready` 200 |
| admin + doctor login (read **and** write) | OK |
| clinical + PHI audit reads through the API | 200 |

Two caveats found during the drill and worth remembering:

* `payments` had **0 rows**, so the financial-data check passed vacuously.
  Re-run this drill once real payments exist.
* A failed backup still leaves a 0-byte `.sql.gz` on disk. The script logs
  `backup failed` correctly, but the file looks like a backup to anyone
  grabbing "the latest" during an incident. Check the size before trusting one.
