import uuid


def new_event_id() -> str:
    return str(uuid.uuid4())