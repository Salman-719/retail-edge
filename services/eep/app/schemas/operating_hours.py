"""Store operating-hours schemas (C2).

Weekday index is Python weekday(): 0 = Monday … 6 = Sunday.
"""
from datetime import time

from pydantic import BaseModel, model_validator


class OperatingHourDay(BaseModel):
    day_of_week: int
    is_open: bool
    open_time: time | None = None
    close_time: time | None = None

    @model_validator(mode="after")
    def _validate(self) -> "OperatingHourDay":
        if not (0 <= self.day_of_week <= 6):
            raise ValueError("day_of_week must be 0..6 (0=Monday)")
        if self.is_open:
            if self.open_time is None or self.close_time is None:
                raise ValueError(
                    f"day {self.day_of_week}: open_time and close_time are required when is_open"
                )
            if self.open_time == self.close_time:
                raise ValueError(
                    f"day {self.day_of_week}: open_time and close_time must differ"
                )
        return self


class OperatingHoursResponse(BaseModel):
    days: list[OperatingHourDay]


class OperatingHoursUpdate(BaseModel):
    """Replace-all payload: exactly one entry per weekday 0..6."""

    days: list[OperatingHourDay]

    @model_validator(mode="after")
    def _all_seven_days(self) -> "OperatingHoursUpdate":
        seen = sorted(d.day_of_week for d in self.days)
        if seen != list(range(7)):
            raise ValueError("operating hours must include each day 0..6 exactly once")
        return self
