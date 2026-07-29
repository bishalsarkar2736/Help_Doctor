import pytest

from app.domain.fsm.appointment_fsm import AppointmentFSM
from app.models.appointment import AppointmentStatus
from app.try_except.exceptions import BadRequestError

S = AppointmentStatus


def test_scheduled_status_removed():
    assert not hasattr(AppointmentStatus, "SCHEDULED")
    assert "SCHEDULED" not in {s.value for s in AppointmentStatus}


def test_checked_in_can_go_straight_to_consultation():
    # New in Phase B: WAITING is optional.
    AppointmentFSM.can_transition(S.CHECKED_IN, S.IN_CONSULTATION)


def test_checked_in_to_waiting_still_allowed():
    AppointmentFSM.can_transition(S.CHECKED_IN, S.WAITING)


def test_confirmed_can_reopen_to_pending_for_reschedule():
    # Reschedule re-opens confirmation.
    AppointmentFSM.can_transition(S.CONFIRMED, S.PENDING)


def test_full_happy_path_is_valid():
    for cur, nxt in [
        (S.PENDING, S.CONFIRMED),
        (S.CONFIRMED, S.CHECKED_IN),
        (S.CHECKED_IN, S.WAITING),
        (S.WAITING, S.IN_CONSULTATION),
        (S.IN_CONSULTATION, S.COMPLETED),
    ]:
        AppointmentFSM.can_transition(cur, nxt)


def test_terminal_states_reject_further_transitions():
    for terminal in (S.COMPLETED, S.CANCELLED, S.NO_SHOW):
        with pytest.raises(BadRequestError):
            AppointmentFSM.can_transition(terminal, S.CONFIRMED)


def test_invalid_skips_rejected():
    with pytest.raises(BadRequestError):
        AppointmentFSM.can_transition(S.PENDING, S.COMPLETED)
    with pytest.raises(BadRequestError):
        AppointmentFSM.can_transition(S.PENDING, S.NO_SHOW)
