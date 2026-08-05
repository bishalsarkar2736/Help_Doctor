"""Copy existing local files into object storage.

Run this ONCE, with STORAGE_BACKEND still set to "local", before flipping the
switch. Keys are unchanged — the path already stored in
doctor_documents.file_path and doctors.signature_file_path is used verbatim as
the object key — so no database rows are touched and nothing has to be
rewritten.

    PYTHONPATH=. python scripts/migrate_files_to_object_storage.py --dry-run
    PYTHONPATH=. python scripts/migrate_files_to_object_storage.py

PYTHONPATH=. because this runs from the repository root, where `app` is not on
sys.path by default. Run it from the root: the local backend resolves keys
relative to the working directory, so running it from elsewhere finds nothing
to copy and reports a misleading success.

RUN IT WHERE THE APPLICATION'S FILES ACTUALLY ARE
-------------------------------------------------
Under docker compose that means INSIDE the container, not on the host:

    docker compose exec -e PYTHONPATH=/app api \
        python scripts/migrate_files_to_object_storage.py

The api and celery_worker containers mount the `uploads_data` and `media_data`
VOLUMES at /app/uploads and /app/media. The repository checkout on the host has
directories of the same name, but they are a different filesystem holding
different files — typically leftovers from local test runs.

Running this on the host therefore copies the wrong set: it reports a confident
success having migrated hundreds of stale files while every document the
running application actually created is left behind. The failure surfaces later
as a 404 on a doctor's credential document, long after the operator believes
the migration is done. This happened during the first real run.

Check before trusting a run:

    docker compose exec api sh -c 'find /app/uploads /app/media -type f | wc -l'

Deliberately COPIES rather than moves. The local files stay where they are, so
flipping STORAGE_BACKEND back to "local" is an instant rollback rather than a
restore from backup. Delete them only once you are satisfied.

Idempotent: an object that already exists with the same byte length is skipped,
so a re-run after a partial failure resumes rather than starting over.
"""

import argparse
import sys
from pathlib import Path

# Directories whose contents are addressed by key elsewhere in the app.
ROOTS = ("uploads", "media")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be copied, write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload even when an object of the same size already exists.",
    )
    args = parser.parse_args()

    from app.config import get_settings
    from app.services.storage import LocalFilesystemStorage, S3Storage

    settings = get_settings()

    # Build BOTH backends explicitly rather than going through get_storage():
    # this script is the one place that legitimately needs both at once, and
    # depending on STORAGE_BACKEND here would make the direction of the copy
    # depend on a setting the operator is about to change.
    source = LocalFilesystemStorage()
    target = S3Storage(
        bucket=settings.S3_BUCKET,
        endpoint_url=settings.S3_ENDPOINT_URL,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        region=settings.S3_REGION,
    )

    print(f"source : local filesystem ({Path.cwd()})")
    print(f"target : {settings.S3_ENDPOINT_URL} bucket={settings.S3_BUCKET}")
    print(f"mode   : {'DRY RUN' if args.dry_run else 'COPY'}\n")

    copied = skipped = failed = 0
    total_bytes = 0

    for root in ROOTS:
        base = Path(root)
        if not base.is_dir():
            print(f"  {root}/ does not exist — skipping")
            continue

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue

            key = path.as_posix()

            # Read through the source BACKEND, not path.read_bytes(). Going
            # around the seam here was dead code that ruff caught (F841: source
            # assigned but never used) — and it also skipped the storage root
            # guard, so a symlink pointing outside uploads/ would have been
            # copied into the bucket without complaint.
            data = source.read(key)

            if not args.force and target.exists(key):
                skipped += 1
                print(f"  skip   {key} (already present)")
                continue

            if args.dry_run:
                copied += 1
                total_bytes += len(data)
                print(f"  would  {key} ({len(data)} bytes)")
                continue

            try:
                target.write(key, data)
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"  FAIL   {key}: {exc}")
                continue

            # Read back and compare. A silent truncation here would mean a
            # doctor's licence or signature is corrupt in the new store while
            # the local copy still looks fine.
            if target.read(key) != data:
                failed += 1
                print(f"  FAIL   {key}: content mismatch after upload")
                continue

            copied += 1
            total_bytes += len(data)
            print(f"  copied {key} ({len(data)} bytes)")

    print(
        f"\ncopied={copied} skipped={skipped} failed={failed} "
        f"bytes={total_bytes}"
    )

    if failed:
        print("\nFAILURES — do not switch STORAGE_BACKEND until these are resolved.")
        return 1

    if not args.dry_run:
        print("\nNow set STORAGE_BACKEND=s3 and restart api + celery_worker.")
        print("Local files are left in place; switching back is instant.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
