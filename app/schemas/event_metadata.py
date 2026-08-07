from enum import Enum
from typing import Optional

from pydantic import BaseModel


class EventSource(str, Enum):
    """Who caused this event: a person, or the system on its own.

    A patient notification is a message from the clinic to the patient. That
    makes sense when a doctor cancels an appointment or a receptionist moves
    one — somebody decided something, and the patient should hear about it.

    It makes much less sense for a scheduled job that marks unattended
    appointments NO_SHOW. The patient already knows they did not attend;
    "Your appointment status changed to NO_SHOW" is a verdict delivered by a
    cron job, up to five minutes late, and on the first run after deployment it
    arrives for every overdue appointment in the history of the clinic at once.

    So events say which they are. SYSTEM is not a reason to stop RECORDING
    anything — the event is still published, the audit entry and the status
    history are still written, and the clinic dashboard still refreshes. It
    only means nobody is told personally.
    """

    USER = "USER"
    SYSTEM = "SYSTEM"


class EventActor(BaseModel):

    id: int
    role: str


class EventMetadata(BaseModel):

    schema_version: int = 1

    # Defaulted, and that default is load-bearing. The outbox stores events as
    # JSON and the worker re-validates them with model_validate under
    # extra="forbid"; every event queued before this field existed has no
    # `source` key. A default means they validate and behave exactly as they
    # did. Without one they would fail validation and land in the dead-letter
    # queue — a schema change that silently breaks the events already in
    # flight.
    #
    # USER is the safe default in the other direction too: a new producer that
    # forgets to set this notifies, which is the behaviour everything had
    # before. Forgetting cannot silently mute a patient.
    source: EventSource = EventSource.USER

    occurred_at: str

    correlation_id: Optional[str] = None

    causation_id: Optional[str] = None

    aggregate_type: str

    aggregate_id: int

    actor: Optional[EventActor] = None