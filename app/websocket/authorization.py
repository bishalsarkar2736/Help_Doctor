"""Who may subscribe to which realtime channel.

A channel is a resource. The dynamic subscribe handler used to take a name from
the client and join it unconditionally, so any authenticated socket could reach
`admin_dashboard:{any_clinic}` or `doctor_queue:{any_doctor}` — which also made
the per-clinic dashboard channel cosmetic, since the default subscription was
only the polite path to a channel anyone could name.

Every rule here mirrors the authorization of the equivalent HTTP resource, so
the socket and the endpoint cannot disagree about who may see a queue:

    doctor_queue:{doctor_id}     staff of that doctor's clinic
                                 (the rule GET /appointments/queue applies)
    admin_dashboard:{clinic_id}  that clinic's admin
    presence_updates             nobody — the channel is no longer published
    anything else                denied

Unknown channels are denied rather than allowed. A channel added later is
unreachable until someone decides who may hear it, which is the failure
direction that costs a bug report rather than a disclosure.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doctor import Doctor
from app.models.user import UserRole

logger = logging.getLogger(__name__)

DOCTOR_QUEUE_PREFIX = "doctor_queue:"
ADMIN_DASHBOARD_PREFIX = "admin_dashboard:"
PRESENCE_CHANNEL = "presence_updates"

CLINIC_STAFF = (UserRole.DOCTOR, UserRole.RECEPTIONIST, UserRole.ADMIN)


def _suffix_id(channel: str, prefix: str) -> int | None:
    """The integer a channel names, or None if it names nothing.

    Deliberately strict: `doctor_queue:1;2` and `doctor_queue:` are not
    resources, and int() is what decides that rather than a regex nobody
    revisits.
    """

    raw = channel[len(prefix):]

    try:
        return int(raw)
    except ValueError:
        return None


async def _caller_clinic_id(db: AsyncSession, user) -> int | None:
    """The clinic this principal acts inside.

    A doctor's clinic lives on their Doctor row; admins and receptionists carry
    it on the user. Reading user.clinic_id for everyone would deny every
    doctor — the asymmetry patients._searcher_clinic_id documents.
    """

    if user.role == UserRole.DOCTOR:
        return await db.scalar(
            select(Doctor.clinic_id).where(Doctor.user_id == user.id)
        )

    return getattr(user, "clinic_id", None)


async def may_subscribe(db: AsyncSession, user, channel: str) -> bool:
    """Whether this principal may join this channel."""

    if channel == PRESENCE_CHANNEL:
        # Denied outright. This granted the channel on role alone, with no
        # clinic predicate, so one clinic's admin received the connect and
        # disconnect of every other tenant's staff and of patients — the same
        # data GET /users/{user_id}/presence refuses them, through another door.
        #
        # Removed rather than scoped because nothing consumes it: the frontend's
        # only sockets handle doctor_queue and notifications, and no client code
        # references presence in any form. Scoping an unconsumed broadcast would
        # be building a feature. Nothing publishes here any more, so the honest
        # answer to "may I join" is no.
        #
        # The named constant stays so this decision is visible at the point
        # anyone would look to re-enable it.
        return False

    if channel.startswith(ADMIN_DASHBOARD_PREFIX):

        if user.role != UserRole.ADMIN:
            return False

        clinic_id = _suffix_id(channel, ADMIN_DASHBOARD_PREFIX)

        return clinic_id is not None and clinic_id == user.clinic_id

    if channel.startswith(DOCTOR_QUEUE_PREFIX):

        if user.role not in CLINIC_STAFF:
            return False

        doctor_id = _suffix_id(channel, DOCTOR_QUEUE_PREFIX)

        if doctor_id is None:
            return False

        caller_clinic_id = await _caller_clinic_id(db, user)

        if caller_clinic_id is None:
            return False

        doctor_clinic_id = await db.scalar(
            select(Doctor.clinic_id).where(Doctor.id == doctor_id)
        )

        return (
            doctor_clinic_id is not None
            and doctor_clinic_id == caller_clinic_id
        )

    return False
