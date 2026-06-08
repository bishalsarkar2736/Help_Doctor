from typing import Optional


# =========================
# COMMON METADATA
# =========================
def build_event_metadata(
    *,
    aggregate_type: str,
    aggregate_id: int,
    occurred_at: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    metadata = {
        "schema_version": 1,
        "occurred_at": occurred_at,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
    }

    if actor_id is not None and actor_role is not None:
        metadata["actor"] = {
            "id": actor_id,
            "role": actor_role,
        }

    return metadata


# =========================
# CANCELLED
# =========================
def build_appointment_cancelled_event(
    *,
    appointment_id: int,
    user_id: int,
    cancelled_by_id: int,
    cancelled_by_role: str,
    occurred_at: str,
    reason: Optional[str],
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "APPOINTMENT_CANCELLED",

        **build_event_metadata(
            aggregate_type="appointment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=cancelled_by_id,
            actor_role=cancelled_by_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "user_id": user_id,
        "appointment_id": appointment_id,

        # TEMPORARY DUPLICATION
        # can remove later because actor already contains this
        "cancelled_by": {
            "id": cancelled_by_id,
            "role": cancelled_by_role,
        },

        "reason": reason or "",
    }

    return {
        "event_type": "APPOINTMENT_CANCELLED",
        "payload": payload,
    }


# =========================
# RESCHEDULED
# =========================
def build_appointment_rescheduled_event(
    *,
    appointment_id: int,
    user_id: int,
    occurred_at: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "APPOINTMENT_RESCHEDULED",

        **build_event_metadata(
            aggregate_type="appointment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "user_id": user_id,
        "appointment_id": appointment_id,
    }

    return {
        "event_type": "APPOINTMENT_RESCHEDULED",
        "payload": payload,
    }


# =========================
# RESCHEDULE REQUEST
# =========================
def build_appointment_reschedule_request_event(
    *,
    appointment_id: int,
    user_id: int,
    occurred_at: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "APPOINTMENT_RESCHEDULE_REQUEST",

        **build_event_metadata(
            aggregate_type="appointment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "user_id": user_id,
        "appointment_id": appointment_id,
    }

    return {
        "event_type": "APPOINTMENT_RESCHEDULE_REQUEST",
        "payload": payload,
    }


# =========================
# CREATED
# =========================
def build_appointment_created_event(
    *,
    appointment_id: int,
    user_id: int,
    doctor_id: int,
    scheduled_at: str,
    occurred_at: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "APPOINTMENT_CREATED",

        **build_event_metadata(
            aggregate_type="appointment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "user_id": user_id,
        "appointment_id": appointment_id,
        "doctor_id": doctor_id,
        "scheduled_at": scheduled_at,
    }

    return {
        "event_type": "APPOINTMENT_CREATED",
        "payload": payload,
    }


# =========================
# CONFIRMED
# =========================
def build_appointment_confirmed_event(
    *,
    appointment_id: int,
    user_id: int,
    occurred_at: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "APPOINTMENT_CONFIRMED",

        **build_event_metadata(
            aggregate_type="appointment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "user_id": user_id,
        "appointment_id": appointment_id,
    }

    return {
        "event_type": "APPOINTMENT_CONFIRMED",
        "payload": payload,
    }


# =========================
# STATUS CHANGED
# =========================
def build_appointment_status_changed_event(
    *,
    appointment_id: int,
    patient_id: int,
    doctor_id: int,
    changed_by: int,
    new_status: str,
    occurred_at: str,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "APPOINTMENT_STATUS_CHANGED",

        **build_event_metadata(
            aggregate_type="appointment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=changed_by,
            actor_role=actor_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "patient_id": patient_id,
        "appointment_id": appointment_id,
        "doctor_id": doctor_id,
        "changed_by": changed_by,
        "new_status": new_status,
    }

    return {
        "event_type": "APPOINTMENT_STATUS_CHANGED",
        "payload": payload,
    }


# =========================
# PAYMENT SUCCESS
# =========================
def build_payment_success_event(
    *,
    appointment_id: int,
    user_id: int,
    occurred_at: str,
    actor_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict:

    payload = {
        "event_type": "PAYMENT_SUCCESS",

        **build_event_metadata(
            aggregate_type="payment",
            aggregate_id=appointment_id,
            occurred_at=occurred_at,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ),

        "user_id": user_id,
        "appointment_id": appointment_id,
    }

    return {
        "event_type": "PAYMENT_SUCCESS",
        "payload": payload,
    }