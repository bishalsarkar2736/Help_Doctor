"""Who may subscribe to which realtime channel.

WHAT WAS WRONG
The dynamic subscribe handler took the channel name from the client and joined
it, with no check of any kind:

    payload = SubscribeMessage.model_validate(data)   # channel: str
    await manager.subscribe(payload.channel, websocket)

So any authenticated socket — a patient's included — could join
`admin_dashboard:{any_clinic}` or `doctor_queue:{any_doctor}` and receive that
clinic's dashboard or that doctor's waiting patients by name.

That also defeated the scoping in b608065. Naming the publisher's channel per
clinic and subscribing admins to their own achieves nothing while a client can
name any channel it likes; the default subscription was merely the polite path
to a channel anyone could reach.

THE RULE
A channel is a resource. Subscribing to one is an authorization decision made
on the same terms as reading the equivalent HTTP resource:

    doctor_queue:{doctor_id}     staff of that doctor's clinic
    admin_dashboard:{clinic_id}  that clinic's admin
    presence_updates             nobody — no longer published
    anything else                denied

Unknown channels are denied rather than allowed, so a channel added later is
unreachable until someone decides who may hear it.
"""

import pytest

from app.models.user import UserRole
from app.websocket.authorization import may_subscribe


def _user(role, clinic_id=None, user_id=1):
    """A principal shaped like the one the socket authenticates.

    A plain object rather than a User row: may_subscribe reads role, id and
    clinic_id, and several of these cases must be decidable without the
    principal existing in the database at all.
    """

    return type(
        "Principal",
        (),
        {"id": user_id, "role": role, "clinic_id": clinic_id},
    )()


# ---------------------------------------------------------------------------
# doctor_queue:{doctor_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receptionist_may_subscribe_to_a_doctor_in_their_clinic(
    db, auth_receptionist, doctor
):
    assert await may_subscribe(
        db, auth_receptionist["user"], f"doctor_queue:{doctor.id}"
    )


@pytest.mark.asyncio
async def test_receptionist_may_not_subscribe_to_another_clinics_doctor(
    db, auth_receptionist, other_clinic_doctor
):
    """THE CASE THE ENDPOINT ALREADY REFUSES. A socket must not be the way
    around it."""

    assert not await may_subscribe(
        db,
        auth_receptionist["user"],
        f"doctor_queue:{other_clinic_doctor['doctor'].id}",
    )


@pytest.mark.asyncio
async def test_a_doctor_may_subscribe_to_their_own_queue(db, auth_doctor):
    assert await may_subscribe(
        db, auth_doctor["user"], f"doctor_queue:{auth_doctor['doctor'].id}"
    )


@pytest.mark.asyncio
async def test_a_doctor_may_subscribe_to_a_colleague_in_the_same_clinic(
    db, auth_doctor, another_doctor
):
    """Same rule as GET /appointments/queue: the boundary is the clinic, not
    the individual. Deliberate, so the socket and the endpoint cannot disagree
    about who may see a queue."""

    assert await may_subscribe(
        db, auth_doctor["user"], f"doctor_queue:{another_doctor.id}"
    )


@pytest.mark.asyncio
async def test_a_patient_may_not_subscribe_to_any_queue(db, doctor):
    assert not await may_subscribe(
        db, _user(UserRole.PATIENT), f"doctor_queue:{doctor.id}"
    )


@pytest.mark.asyncio
async def test_an_unknown_doctor_id_is_refused(db, auth_receptionist):
    assert not await may_subscribe(
        db, auth_receptionist["user"], "doctor_queue:999999"
    )


@pytest.mark.asyncio
async def test_a_malformed_doctor_id_is_refused(db, auth_receptionist):
    """`doctor_queue:` names a resource; a non-numeric suffix names nothing."""

    for channel in ("doctor_queue:abc", "doctor_queue:", "doctor_queue:1;2"):
        assert not await may_subscribe(
            db, auth_receptionist["user"], channel
        ), channel


# ---------------------------------------------------------------------------
# admin_dashboard:{clinic_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_may_subscribe_to_their_own_clinics_dashboard(
    db, auth_admin, default_clinic
):
    assert await may_subscribe(
        db, auth_admin["user"], f"admin_dashboard:{default_clinic.id}"
    )


@pytest.mark.asyncio
async def test_an_admin_may_not_subscribe_to_another_clinics_dashboard(
    db, auth_admin, second_clinic
):
    """The hole that made b608065 cosmetic."""

    assert not await may_subscribe(
        db, auth_admin["user"], f"admin_dashboard:{second_clinic.id}"
    )


@pytest.mark.asyncio
async def test_non_admins_may_not_subscribe_to_a_dashboard(
    db, auth_receptionist, default_clinic
):
    for principal in (
        auth_receptionist["user"],
        _user(UserRole.DOCTOR, clinic_id=default_clinic.id),
        _user(UserRole.PATIENT),
    ):
        assert not await may_subscribe(
            db, principal, f"admin_dashboard:{default_clinic.id}"
        )


# ---------------------------------------------------------------------------
# Everything else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_channel_is_refused(db, auth_admin):
    for channel in ("", "chat", "ws_notifications", "doctor_queue", "*"):
        assert not await may_subscribe(db, auth_admin["user"], channel), channel


@pytest.mark.asyncio
async def test_presence_updates_is_refused_to_everyone(
    db, auth_admin, auth_receptionist
):
    """SUPERSEDED. This asserted that any ADMIN could join presence_updates,
    matching the auto-subscription on connect.

    Both are gone. The channel carried every user's connect and disconnect with
    no clinic predicate, so one clinic's admin saw every other tenant's staff
    and every patient — the data GET /users/{user_id}/presence refuses them.
    Nothing consumed it, so it is no longer published rather than re-scoped.

    The deny-cases below are unchanged; only the admin allow-case flipped.
    """

    assert not await may_subscribe(db, auth_admin["user"], "presence_updates")
    assert not await may_subscribe(
        db, auth_receptionist["user"], "presence_updates"
    )
