# File storage

Uploaded files — doctor credential documents, clinic logos, doctor signatures —
go through one seam, `app/services/storage.py`, with two backends behind it.

| `STORAGE_BACKEND` | where files live | when to use |
|---|---|---|
| `local` (default) | `uploads/` and `media/` directories | single api replica |
| `s3` | S3-compatible object storage (MinIO in compose) | **required** for >1 replica |

## Why this matters before scaling out

With `local`, compose shares the `uploads_data` and `media_data` volumes
between the api and celery_worker containers, so both see the same files. That
breaks the moment a second api replica runs elsewhere: an upload lands on
replica A's disk, the database row points at a path that exists only there, and
a download served by replica B is a 404. Nothing errors at upload time — the
failure appears later, when someone tries to open a document.

## Keys are paths, so there is no data migration

A key is the exact string already stored in `doctor_documents.file_path` and
`doctors.signature_file_path`, e.g. `uploads/doctor_documents/doctor1_LICENSE_
7c13fc.pdf`. Both backends use it verbatim, so no database rows change and a
row written under one backend resolves under the other.

## Switching to object storage

```bash
docker compose up -d minio minio_init          # bucket is created for you

# 1. Copy existing files, with STORAGE_BACKEND still "local".
#    MUST run inside the container — see the warning below.
docker compose exec -e PYTHONPATH=/app api \
    python scripts/migrate_files_to_object_storage.py --dry-run
docker compose exec -e PYTHONPATH=/app api \
    python scripts/migrate_files_to_object_storage.py

# 2. Flip the switch
sed -i 's/^STORAGE_BACKEND=local/STORAGE_BACKEND=s3/' .env.docker
docker compose up -d api celery_worker
```

### Run the migration inside the container

The api container mounts **volumes** at `/app/uploads` and `/app/media`. The
repository checkout on the host has directories of the same name, but they are
a different filesystem holding different files — usually leftovers from local
test runs.

Running the migration on the host copies the wrong set. It reports a confident
success having migrated hundreds of stale files while every document the
running application actually created is left behind, and the failure only
surfaces later as a 404 on a doctor's licence. This happened on the first real
run here: 318 stale files copied, 3 real ones missed.

Check what you are about to migrate:

```bash
docker compose exec api sh -c 'find /app/uploads /app/media -type f | wc -l'
```

### Rolling back

The migration **copies**; it never deletes. Local files stay in place, so
reverting is `STORAGE_BACKEND=local` and a restart — no restore required.

## Serving

`app/api/routes/files.py` serves `/media/...` and `/uploads/...` through the
seam, so the same URLs work under either backend. It replaced a
`StaticFiles(directory="media")` mount, which reads the local disk directly and
would have silently served nothing under `s3` — every signature in the UI a
broken image, every prescription PDF unsigned.

Those routes are **unauthenticated**, because browsers load them as `<img>`
tags and image requests carry no `Authorization` header. So the allowlist is
security-critical:

```python
PUBLIC_PREFIXES = ("media/signatures/", "uploads/clinic_logos/")
```

Credential documents live under `uploads/doctor_documents/` and are **not**
served there. They stay behind the authenticated, clinic-scoped route in
`admin_doctors.py`. A blanket `/uploads` mount would have published every
practitioner's BMDC certificate and medical licence to anyone who could guess a
filename.

## Known limitations

* **Signature URLs are guessable** (`media/signatures/doctor_<id>.png`) and
  public to anyone holding the URL. Unchanged from the previous behaviour, but
  worth fixing with random keys plus a data migration.
* **boto3 is synchronous**, and so is the `Storage` protocol it implements, so
  calls block the event loop for the duration of an object-store request.
  Acceptable at current sizes (documents capped at 5 MB, store on the same
  network); the fix is an async protocol, which the seam makes tractable.
* **Object storage is not backed up** by `db_backup`, which covers Postgres
  only. See `docs/BACKUP_RESTORE.md`.
* MinIO is published on **127.0.0.1:9101** (API) and **9102** (console), not
  the usual 9000/9001 — portainer and prometheus-node-exporter commonly hold
  those, and a bind failure aborts `docker compose up` for the whole stack.
