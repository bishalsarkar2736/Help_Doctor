from datetime import datetime, timezone,timedelta
from app.core.time import utc_now


def get_today_range():
    now = utc_now()

    start = datetime(
        now.year,
        now.month,
        now.day,
        tzinfo=timezone.utc,
    )

    end = start + timedelta(days=1)

    return start, end



def get_month_range():
    
    today = utc_now().date()

    month_start = datetime(
        today.year,
        today.month,
        1,
        tzinfo=timezone.utc,
    )

    if today.month == 12:
        next_month = datetime(
            today.year + 1,
            1,
            1,
            tzinfo=timezone.utc,
        )
    else:
        next_month = datetime(
            today.year,
            today.month + 1,
            1,
            tzinfo=timezone.utc,
        )

    return month_start, next_month