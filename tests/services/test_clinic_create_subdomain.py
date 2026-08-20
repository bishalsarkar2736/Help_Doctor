"""Creating a clinic with a subdomain.

The rule and the schema wiring are covered elsewhere; these tests are about
persistence and about which authority decides uniqueness. The pre-check in
create_clinic exists to give a readable message, but two concurrent requests
can both pass it — so the last test drives the path where it does not fire and
asserts the database is still the thing that refuses.
"""

import pytest
from sqlalchemy import select

from app.models.clinic import Clinic
from app.schemas.clinic_schema import ClinicCreate
from app.services import clinic_service
from app.services.clinic_service import create_clinic
from app.try_except.exceptions import BadRequestError


async def _create(db, **kwargs) -> Clinic:
    return await create_clinic(db=db, payload=ClinicCreate(**kwargs))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_supplied_subdomain_is_persisted(db):
    clinic = await _create(db, name="City Care", subdomain="citycare")

    stored = await db.scalar(select(Clinic).where(Clinic.id == clinic.id))

    assert stored.subdomain == "citycare"


@pytest.mark.asyncio
async def test_a_clinic_can_be_created_without_a_subdomain(db):
    """The normal case: DNS is decided later, or never."""
    clinic = await _create(db, name="No DNS Clinic")

    assert clinic.subdomain is None


@pytest.mark.asyncio
async def test_the_subdomain_is_stored_normalised(db):
    """Uppercase reaches the schema, lowercase reaches the column — otherwise
    the case-insensitive unique index and the stored value disagree."""
    clinic = await _create(db, name="Mixed Case", subdomain="  CityCare  ")

    assert clinic.subdomain == "citycare"


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_duplicate_subdomain_is_refused(db):
    await _create(db, name="First Clinic", subdomain="shared")

    with pytest.raises(BadRequestError) as exc:
        await _create(db, name="Second Clinic", subdomain="shared")

    assert "subdomain" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_a_duplicate_differing_only_in_case_is_refused(db):
    """DNS does not distinguish case, so neither may the check."""
    await _create(db, name="First Clinic", subdomain="shared")

    with pytest.raises(BadRequestError):
        await _create(db, name="Second Clinic", subdomain="SHARED")


@pytest.mark.asyncio
async def test_a_duplicate_name_still_reports_the_name(db):
    """The two unique indexes must not be confused for one another: a caller
    told to change the subdomain when the name collided would be misled."""
    await _create(db, name="City Care", subdomain="one")

    with pytest.raises(BadRequestError) as exc:
        await _create(db, name="city care", subdomain="two")

    assert "name" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_several_clinics_may_have_no_subdomain(db):
    """NULLs are not compared by the unique index. If they were, only one
    clinic on the platform could exist without a hostname."""
    first = await _create(db, name="Alpha Clinic")
    second = await _create(db, name="Beta Clinic")

    assert first.subdomain is None and second.subdomain is None


# ---------------------------------------------------------------------------
# The race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_refuses_a_duplicate_the_pre_check_missed(
    db, monkeypatch
):
    """The pre-check is a courtesy; uq_clinic_subdomain_lower is the guarantee.

    Two concurrent creations can both find the subdomain free and both proceed
    to insert. That window is simulated here by making the pre-check answer
    "free" for a subdomain that is already taken — the caller must still get a
    clean 400 from the constraint rather than a 500.
    """
    await _create(db, name="Incumbent Clinic", subdomain="contested")

    async def _always_free(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(clinic_service, "_subdomain_taken", _always_free)

    # Both paths raise the same message, so the assertion below would pass even
    # if the pre-check had fired and the constraint were never reached. Record
    # which one actually ran.
    from_database = []
    original = clinic_service._duplicate_error

    def _record(error):
        from_database.append(error)
        return original(error)

    monkeypatch.setattr(clinic_service, "_duplicate_error", _record)

    with pytest.raises(BadRequestError) as exc:
        await _create(db, name="Challenger Clinic", subdomain="contested")

    assert "subdomain" in str(exc.value).lower()
    assert from_database, (
        "the refusal came from the pre-check, not the unique index — this test "
        "did not exercise the race it claims to"
    )
