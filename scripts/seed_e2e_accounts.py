"""Seed deterministic accounts for the Playwright end-to-end suite.

Every role gets its OWN password. A shared password is convenient but it means a
test can pass while authenticating as the wrong role — the exact class of bug
these tests exist to catch — and it makes a leaked credential usable everywhere.

Writes the credentials as JSON so the Playwright config can read them. Run from
the Help_Doctor directory with the stack up:

    python scripts/seed_e2e_accounts.py ../helpdoctor-frontend/e2e/.accounts.json

Idempotent: safe to re-run before every suite.
"""

import asyncio
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.postgres import AsyncSessionLocal
from app.models.clinic import Clinic
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.security.jwt import hash_password

# One distinct password per role. Long, unrelated to each other, and never
# reused across roles so a test cannot silently authenticate as the wrong one.
ACCOUNTS: list[dict] = [
    {
        "key": "patient",
        "email": "e2e.patient@example.com",
        "password": "Pt-Kestrel-7194-Wharf",
        "role": UserRole.PATIENT,
        "full_name": "E2E Patient",
    },
    {
        "key": "doctor",
        "email": "e2e.doctor@example.com",
        "password": "Dr-Basalt-3826-Lantern",
        "role": UserRole.DOCTOR,
        "full_name": "Dr E2E Doctor",
    },
    {
        "key": "receptionist",
        "email": "e2e.reception@example.com",
        "password": "Rc-Marlow-5513-Thicket",
        "role": UserRole.RECEPTIONIST,
        "full_name": "E2E Receptionist",
    },
    {
        "key": "admin",
        "email": "e2e.admin@example.com",
        "password": "Ad-Quarry-9068-Fathom",
        "role": UserRole.ADMIN,
        "full_name": "E2E Clinic Admin",
    },
    {
        # A PENDING applicant so the admin-approval test always has something
        # real to approve. Re-seeding resets them to PENDING, which keeps the
        # test idempotent — otherwise it passes once and then skips forever.
        "key": "pending_doctor",
        "email": "e2e.pending@example.com",
        "password": "Pd-Alcove-6329-Turnstile",
        "role": UserRole.DOCTOR,
        "full_name": "Dr E2E Pending",
    },
    {
        # Second PENDING applicant: the approval test consumes the first, and
        # the rejection test needs one of its own to stay deterministic.
        "key": "pending_doctor_2",
        "email": "e2e.pending2@example.com",
        "password": "P2-Ridgeway-8157-Cinder",
        "role": UserRole.DOCTOR,
        "full_name": "Dr E2E Pending Two",
    },
    {
        "key": "super_admin",
        "email": "e2e.super@example.com",
        "password": "Sa-Vellum-2457-Beacon",
        "role": UserRole.SUPER_ADMIN,
        "full_name": "E2E Super Admin",
    },
]


# Every address this script owns. Used both to seed and to purge.
E2E_EMAIL_PREFIX = "e2e."


def _guard_environment() -> None:
    """Refuse to run anywhere that is not explicitly development or testing.

    This file contains plaintext passwords for ADMIN and SUPER_ADMIN accounts,
    in source control. Seeding a production database would create
    known-credential administrator logins — so the environment check is the
    security control, not a convenience.
    """

    env = get_settings().ENV
    if env not in ("development", "testing"):
        raise SystemExit(
            f"refusing to run: ENV={env!r}. This script creates accounts with "
            "publicly known passwords and is for development/testing only."
        )


async def purge() -> int:
    """Remove every account this script created.

    Test runs accumulate accounts (each registration and invitation makes a new
    one), and they are all active logins. Left behind they are dead weight at
    best and unattended credentials at worst.
    """

    _guard_environment()

    async with AsyncSessionLocal() as db:
        users = (
            await db.scalars(
                select(User).where(User.email.like(f"{E2E_EMAIL_PREFIX}%"))
            )
        ).all()

        removed = 0
        for user in users:
            # Medical/financial FKs are RESTRICT, so a hard delete can fail by
            # design. Soft-delete instead — the account can no longer be used.
            user.is_active = False
            if user.deleted_at is None:
                user.deleted_at = datetime.now(UTC)
                removed += 1

        await db.commit()
        return removed


async def seed() -> dict:
    _guard_environment()

    async with AsyncSessionLocal() as db:
        clinic = await db.scalar(select(Clinic).order_by(Clinic.id))
        if clinic is None:
            raise SystemExit(
                "No clinic exists. Bootstrap one before seeding e2e accounts."
            )

        out: dict = {"clinicId": clinic.id, "accounts": {}}

        for spec in ACCOUNTS:
            user = await db.scalar(
                select(User).where(User.email == spec["email"])
            )

            if user is None:
                user = User(email=spec["email"], role=spec["role"])
                db.add(user)

            user.hashed_password = hash_password(spec["password"])
            user.full_name = spec["full_name"]
            user.role = spec["role"]
            user.is_active = True
            user.is_email_verified = True
            user.deleted_at = None
            user.auth_provider = "LOCAL"
            # Patients and the platform super admin are not clinic-scoped.
            user.clinic_id = (
                None
                if spec["role"] in (UserRole.PATIENT, UserRole.SUPER_ADMIN)
                else clinic.id
            )

            await db.flush()

            # Role-specific profile rows the UI needs in order to render.
            if spec["role"] == UserRole.PATIENT:
                patient = await db.scalar(
                    select(Patient).where(Patient.user_id == user.id)
                )
                if patient is None:
                    db.add(
                        Patient(
                            user_id=user.id,
                            phone="01700000001",
                            address="Dhaka",
                            date_of_birth=date(1990, 5, 17),
                            gender="MALE",
                        )
                    )

            if spec["role"] == UserRole.DOCTOR:
                pending = spec["key"].startswith("pending_doctor")
                doctor = await db.scalar(
                    select(Doctor).where(Doctor.user_id == user.id)
                )
                if doctor is None:
                    doctor = Doctor(user_id=user.id)
                    db.add(doctor)
                doctor.clinic_id = clinic.id
                doctor.specialization = "General Medicine"
                doctor.experience_years = 8
                doctor.bio = "Seeded for end-to-end tests."
                doctor.consultation_fee = 500
                if pending:
                    # Reset to PENDING every run so approval can be re-tested.
                    doctor.status = DoctorStatus.PENDING
                    doctor.approved_at = None
                    doctor.approved_by = None
                    doctor.rejection_reason = None
                else:
                    # APPROVED so patient booking can find and book them.
                    doctor.status = DoctorStatus.APPROVED
                    doctor.approved_at = datetime.now(UTC)

            out["accounts"][spec["key"]] = {
                "email": spec["email"],
                "password": spec["password"],
                "role": spec["role"].value,
            }

        await db.commit()
        return out


async def main() -> None:
    if "--purge" in sys.argv:
        count = await purge()
        print(f"purged {count} e2e account(s)")
        return

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "e2e-accounts.json")
    data = await seed()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n")
    print(f"seeded {len(data['accounts'])} accounts -> {target}")
    for key, acc in data["accounts"].items():
        print(f"  {key:14} {acc['email']}")


if __name__ == "__main__":
    asyncio.run(main())
