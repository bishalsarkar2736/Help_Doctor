"""Shapes for clinic opening hours and holidays.

Validated on the way in so the reader never has to cope with a half-formed
range. The assistant states these as fact — "we close at 9 PM" — and a
close time that precedes its open time, or a weekday key of "Monday" where the
reader expects "0", would either crash a public answer or silently produce a
wrong one.
"""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OpeningRange(BaseModel):
    """One continuous period the clinic is open."""

    model_config = ConfigDict(extra="forbid")

    open: time
    close: time

    @model_validator(mode="after")
    def _close_after_open(self) -> "OpeningRange":
        if self.close <= self.open:
            raise ValueError(
                f"close ({self.close}) must be after open ({self.open})"
            )

        return self


class OpeningHoursUpdate(BaseModel):
    """The full week. Anything not listed is closed.

    Replaces rather than merges: a partial update would make removing a day
    impossible, and "we no longer open on Sunday" is a change a clinic has to
    be able to make.
    """

    model_config = ConfigDict(extra="forbid")

    # Monday=0, matching date.weekday() and DoctorAvailability.day_of_week.
    days: dict[int, list[OpeningRange]] = Field(default_factory=dict)

    @field_validator("days")
    @classmethod
    def _valid_weekdays(
        cls, value: dict[int, list[OpeningRange]]
    ) -> dict[int, list[OpeningRange]]:
        for weekday in value:
            if not 0 <= weekday <= 6:
                raise ValueError(
                    f"weekday must be 0 (Monday) to 6 (Sunday), got {weekday}"
                )

        return value

    @model_validator(mode="after")
    def _no_overlaps(self) -> "OpeningHoursUpdate":
        # Overlapping ranges are not wrong to store but are always a mistake to
        # enter, and they make "when do you close?" ambiguous.
        for weekday, ranges in self.days.items():
            ordered = sorted(ranges, key=lambda r: r.open)

            for earlier, later in zip(ordered, ordered[1:]):
                if later.open < earlier.close:
                    raise ValueError(
                        f"weekday {weekday} has overlapping ranges: "
                        f"{earlier.open}-{earlier.close} and "
                        f"{later.open}-{later.close}"
                    )

        return self

    def to_storage(self) -> dict:
        """The JSON form the column holds — string keys, "HH:MM" times."""
        return {
            str(weekday): [
                {
                    "open": entry.open.strftime("%H:%M"),
                    "close": entry.close.strftime("%H:%M"),
                }
                for entry in ranges
            ]
            for weekday, ranges in self.days.items()
            # A weekday mapped to an empty list is the same as an absent one;
            # storing both would give the reader two ways to say "closed".
            if ranges
        }


class Holiday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    name: str = Field(min_length=1, max_length=120)


class HolidayScheduleUpdate(BaseModel):
    """Dates the clinic is closed regardless of its usual hours."""

    model_config = ConfigDict(extra="forbid")

    holidays: list[Holiday] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_dates(self) -> "HolidayScheduleUpdate":
        seen = [holiday.date for holiday in self.holidays]

        duplicates = {d for d in seen if seen.count(d) > 1}

        if duplicates:
            raise ValueError(
                f"duplicate holiday dates: {sorted(d.isoformat() for d in duplicates)}"
            )

        return self

    def to_storage(self) -> list[dict]:
        return [
            {"date": holiday.date.isoformat(), "name": holiday.name}
            for holiday in sorted(self.holidays, key=lambda h: h.date)
        ]
