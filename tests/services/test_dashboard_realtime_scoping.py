"""The realtime admin dashboard belongs to one clinic.

WHAT WAS WRONG
publish_dashboard_update computes ONE clinic's overview and broadcast it to a
channel named for nobody:

    overview = await get_dashboard_overview(db=db, clinic_id=clinic_id)
    await manager.broadcast_channel("admin_dashboard", {... "data": overview})

Every ADMIN subscribes to that literal channel when their socket connects
(websocket/routes.py), so the channel holds every clinic's admins at once. The
publisher is called from handle_appointment_transition_side_effects on every
transition into CHECKED_IN, WAITING, IN_CONSULTATION or COMPLETED — so routine
clinic activity pushed one clinic's dashboard to all of them.

This is the same shape as the notify_admins fan-out (fixed in 5e3827b): the
caller was correctly scoped and the delivery was not. The payload here is much
richer than that one — it is a clinic's dashboard overview, not an id and a
boolean.

WHAT THESE TESTS PIN
The channel is per-clinic, and a subscriber to one clinic's channel receives
nothing published for another. Asserted by driving the real ConnectionManager
with stub sockets rather than by reading the channel name, because a name that
looks scoped and a delivery that is scoped are different claims.
"""

import pytest

from app.services.realtime_dashboard_service import (
    dashboard_channel,
    publish_dashboard_update,
)
from app.websocket.manager import manager


class StubSocket:
    """The only thing broadcast_channel asks of a socket is send_json."""

    def __init__(self):
        self.received = []

    async def send_json(self, data):
        self.received.append(data)


@pytest.fixture
def clean_channels():
    """The manager is a module-level singleton shared across the suite."""

    before = dict(manager.channels)
    manager.channels.clear()
    yield
    manager.channels.clear()
    manager.channels.update(before)


# ---------------------------------------------------------------------------


def test_the_channel_name_is_per_clinic():
    assert dashboard_channel(1) != dashboard_channel(2)
    assert "1" in dashboard_channel(1)


@pytest.mark.asyncio
async def test_an_update_reaches_only_its_own_clinics_admins(
    db, default_clinic, second_clinic, clean_channels
):
    """THE PROPERTY. Two admin sockets, two clinics, one update."""

    ours = StubSocket()
    theirs = StubSocket()

    await manager.subscribe(dashboard_channel(default_clinic.id), ours)
    await manager.subscribe(dashboard_channel(second_clinic.id), theirs)

    await publish_dashboard_update(db=db, clinic_id=default_clinic.id)

    assert len(ours.received) == 1, "the clinic's own admin was not updated"

    assert theirs.received == [], (
        "another clinic's admin received a dashboard update for a clinic they "
        "have no relationship with"
    )


@pytest.mark.asyncio
async def test_each_clinic_receives_its_own_update(
    db, default_clinic, second_clinic, clean_channels
):
    """The paired allow-case: scoping must not cost either clinic its own
    dashboard, which 'deliver to nobody' would also satisfy."""

    ours = StubSocket()
    theirs = StubSocket()

    await manager.subscribe(dashboard_channel(default_clinic.id), ours)
    await manager.subscribe(dashboard_channel(second_clinic.id), theirs)

    await publish_dashboard_update(db=db, clinic_id=default_clinic.id)
    await publish_dashboard_update(db=db, clinic_id=second_clinic.id)

    assert len(ours.received) == 1
    assert len(theirs.received) == 1


@pytest.mark.asyncio
async def test_nothing_is_published_to_an_unscoped_channel(
    db, default_clinic, clean_channels
):
    """A subscriber to the old global name must now receive nothing.

    This is what fails if the channel is renamed at the publisher but some
    caller still broadcasts to the bare name.
    """

    legacy = StubSocket()
    await manager.subscribe("admin_dashboard", legacy)

    await publish_dashboard_update(db=db, clinic_id=default_clinic.id)

    assert legacy.received == []


def test_admins_are_subscribed_to_their_own_clinics_channel():
    """The other half of the boundary: a scoped publisher delivers nothing if
    the socket is still subscribed to the shared name.

    Read structurally from the connect handler, since establishing a real
    authenticated WebSocket session is a different test's job.
    """

    import ast
    import pathlib

    import app.websocket.routes as module

    source = pathlib.Path(module.__file__).read_text()
    tree = ast.parse(source)

    subscribes = [
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "subscribe"
        and node.args
    ]

    dashboard_subscriptions = [
        s for s in subscribes if "dashboard" in s.lower()
    ]

    assert dashboard_subscriptions, "admins no longer subscribe to a dashboard"

    for subscription in dashboard_subscriptions:
        assert subscription != "'admin_dashboard'", (
            "admins are subscribed to the shared, unscoped dashboard channel"
        )
        assert "clinic" in subscription.lower(), (
            f"dashboard subscription is not clinic-scoped: {subscription}"
        )
