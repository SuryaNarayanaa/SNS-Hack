from __future__ import annotations

from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SleepScheduleBase(BaseModel):
    bedtime_local: time = Field(...)
    wake_time_local: time = Field(...)
    timezone: str = Field(...)
    active_days: list[int] = Field(..., min_length=1, max_length=7)
    target_duration_minutes: int | None = Field(None, ge=1)
    auto_set_alarm: bool = False
    show_stats_auto: bool = True
    metadata: dict[str, Any] | None = None

    @field_validator("active_days")
    @classmethod
    def validate_active_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("active_days must contain integers 0..6")
        # dedupe preserve order
        seen: set[int] = set()
        out: list[int] = []
        for d in value:
            if d not in seen:
                out.append(d)
                seen.add(d)
        return out


class SleepScheduleCreate(SleepScheduleBase):
    pass


class SleepScheduleUpdate(BaseModel):
    bedtime_local: time | None = None
    wake_time_local: time | None = None
    timezone: str | None = None
    active_days: list[int] | None = None
    target_duration_minutes: int | None = Field(default=None, ge=1)
    auto_set_alarm: bool | None = None
    show_stats_auto: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("active_days")
    @classmethod
    def validate_active_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("active_days must contain integers 0..6")
        seen: set[int] = set()
        out: list[int] = []
        for d in value:
            if d not in seen:
                out.append(d)
                seen.add(d)
        return out

    @model_validator(mode="after")
    def ensure_any(self) -> "SleepScheduleUpdate":
        if not any(getattr(self, k) is not None for k in self.model_fields):
            raise ValueError("At least one field is required")
        return self


class SleepActivateRequest(BaseModel):
    is_active: bool = True


class SleepSessionStart(BaseModel):
    schedule_id: int | None = None
    device_source: str | None = None
    in_bed_start_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class SleepStagePatch(BaseModel):
    stage: str
    start_at: datetime
    end_at: datetime
    movement_index: float | None = None
    heart_rate_avg: float | None = None


class SleepSessionComplete(BaseModel):
    end_at: datetime | None = None
    awake_minutes: float | None = None
    metadata: dict[str, Any] | None = None
