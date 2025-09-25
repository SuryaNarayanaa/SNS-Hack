"""Sleep quality API routes."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator, field_validator

from auth import get_user_by_token
from db import db_session


router = APIRouter(prefix="/sleep", tags=["sleep"])
bearer_scheme = HTTPBearer(auto_error=False)


class SleepScheduleBase(BaseModel):
	bedtime_local: time = Field(..., description="Target sleep start time in local clock")
	wake_time_local: time = Field(..., description="Target wake time in local clock")
	timezone: str = Field(..., description="IANA timezone identifier")
	active_days: list[int] = Field(..., min_length=1, max_length=7, description="Days of week 0=Mon .. 6=Sun")
	target_duration_minutes: int | None = Field(None, ge=1, description="Desired sleep duration in minutes")
	auto_set_alarm: bool = Field(default=False)
	show_stats_auto: bool = Field(default=True)
	metadata: dict[str, Any] | None = Field(default=None)

	@field_validator("active_days")
	@classmethod
	def validate_active_days(cls, value: list[int]) -> list[int]:
		if any(day < 0 or day > 6 for day in value):
			raise ValueError("active_days must contain integers between 0 and 6")
		seen: set[int] = set()
		ordered: list[int] = []
		for day in value:
			if day not in seen:
				ordered.append(day)
				seen.add(day)
		return ordered


class SleepScheduleCreate(SleepScheduleBase):
	"""Payload for creating a new sleep schedule."""


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
			raise ValueError("active_days must contain integers between 0 and 6")
		seen: set[int] = set()
		ordered: list[int] = []
		for day in value:
			if day not in seen:
				ordered.append(day)
				seen.add(day)
		return ordered

	@model_validator(mode="after")
	def ensure_fields_present(self) -> "SleepScheduleUpdate":
		if not any(
			getattr(self, attr) is not None
			for attr in (
				"bedtime_local",
				"wake_time_local",
				"timezone",
				"active_days",
				"target_duration_minutes",
				"auto_set_alarm",
				"show_stats_auto",
				"is_active",
				"metadata",
			)
		):
			raise ValueError("At least one field must be provided for update")
		return self


def _time_to_string(value: time | None) -> str | None:
	if value is None:
		return None
	return value.strftime("%H:%M:%S")


def _serialize_schedule(record: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": record["id"],
		"bedtime_local": _time_to_string(record.get("bedtime_local")),
		"wake_time_local": _time_to_string(record.get("wake_time_local")),
		"timezone": record.get("timezone"),
		"active_days": list(record.get("active_days") or []),
		"target_duration_minutes": record.get("target_duration_minutes"),
		"auto_set_alarm": record.get("auto_set_alarm"),
		"show_stats_auto": record.get("show_stats_auto"),
		"is_active": record.get("is_active"),
		"metadata": record.get("metadata"),
		"created_at": record.get("created_at").isoformat() if record.get("created_at") else None,
		"updated_at": record.get("updated_at").isoformat() if record.get("updated_at") else None,
	}


async def _get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> dict[str, Any]:
	if credentials is None:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

	token = credentials.credentials
	user = await get_user_by_token(token)
	if not user:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

	return user | {"token": token}


@router.get("/schedule")
async def get_active_schedule(current_user: dict[str, Any] = Depends(_get_current_user)) -> dict[str, Any]:
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			SELECT id, bedtime_local, wake_time_local, timezone, active_days, target_duration_minutes,
				   auto_set_alarm, show_stats_auto, is_active, metadata, created_at, updated_at
			FROM sleep_schedule
			WHERE user_id = $1 AND is_active = TRUE
			ORDER BY updated_at DESC
			LIMIT 1
			""",
			current_user["id"],
		)
	return {"schedule": _serialize_schedule(row) if row else None}


@router.post("/schedule", status_code=status.HTTP_201_CREATED)
async def create_schedule(
	payload: SleepScheduleCreate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	async with db_session() as conn:
		await conn.execute(
			"UPDATE sleep_schedule SET is_active = FALSE WHERE user_id = $1",
			current_user["id"],
		)
		row = await conn.fetchrow(
			"""
			INSERT INTO sleep_schedule (
				user_id, bedtime_local, wake_time_local, timezone, active_days,
				target_duration_minutes, auto_set_alarm, show_stats_auto, is_active, metadata
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,TRUE,$9)
			RETURNING id, bedtime_local, wake_time_local, timezone, active_days,
					  target_duration_minutes, auto_set_alarm, show_stats_auto, is_active,
					  metadata, created_at, updated_at
			""",
			current_user["id"],
			payload.bedtime_local,
			payload.wake_time_local,
			payload.timezone,
			payload.active_days,
			payload.target_duration_minutes,
			payload.auto_set_alarm,
			payload.show_stats_auto,
			payload.metadata,
		)

	return {"schedule": _serialize_schedule(row)}


@router.patch("/schedule/{schedule_id}")
async def update_schedule(
	schedule_id: int,
	payload: SleepScheduleUpdate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	updates = payload.model_dump(exclude_none=True)

	async with db_session() as conn:
		assignments: list[str] = []
		params: list[Any] = []
		for column in (
			"bedtime_local",
			"wake_time_local",
			"timezone",
			"active_days",
			"target_duration_minutes",
			"auto_set_alarm",
			"show_stats_auto",
			"is_active",
			"metadata",
		):
			if column in updates:
				assignments.append(f"{column} = ${len(params) + 1}")
				params.append(updates[column])

		assignments.append("updated_at = now()")
		params.extend([current_user["id"], schedule_id])

		row = await conn.fetchrow(
			f"""
			UPDATE sleep_schedule
			SET {', '.join(assignments)}
			WHERE user_id = ${len(params) - 1} AND id = ${len(params)}
			RETURNING id, bedtime_local, wake_time_local, timezone, active_days,
					  target_duration_minutes, auto_set_alarm, show_stats_auto, is_active,
					  metadata, created_at, updated_at
			""",
			*params,
		)

		if row is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

		if updates.get("is_active"):
			await conn.execute(
				"UPDATE sleep_schedule SET is_active = FALSE WHERE user_id = $1 AND id <> $2",
				current_user["id"],
				schedule_id,
			)

	return {"schedule": _serialize_schedule(row)}

