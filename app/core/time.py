from datetime import timezone,datetime

UTC = timezone.utc

def utc_now() -> datetime:
    return datetime.now(UTC)



def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
