"""Pydantic schemas for the Mood Tracker domain."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


MOOD_VALUE_LABELS: Dict[int, str] = {
	0: "depressed",
	1: "sad",
	2: "neutral",
	3: "happy",
	4: "joyful",
	5: "overjoyed",
}


def mood_label_for(value: int) -> str:
	"""Return the canonical label for a mood value."""
	try:
		return MOOD_VALUE_LABELS[value]
	except KeyError as exc:  # pragma: no cover - defensive guard
		raise ValueError(f"Unsupported mood value: {value}") from exc


class MoodEntryBase(BaseModel):
	mood_value: int = Field(..., ge=0, le=5)
	note: Optional[str] = Field(default=None, max_length=2000)
	improvement_flag: Optional[bool] = None
	metadata: Optional[Dict[str, Any]] = None

	@field_validator("mood_value")
	@classmethod
	def _validate_mood_value(cls, value: int) -> int:
		if value not in MOOD_VALUE_LABELS:
			raise ValueError("mood_value must be between 0 and 5")
		return value


class MoodEntryCreate(MoodEntryBase):
	"""Payload for creating a mood entry."""


class MoodEntryUpdate(BaseModel):
	note: Optional[str] = Field(default=None, max_length=2000)
	improvement_flag: Optional[bool] = None
	metadata: Optional[Dict[str, Any]] = None

	@field_validator("note")
	@classmethod
	def _validate_note(cls, note: Optional[str]) -> Optional[str]:
		if note is None:
			return note
		return note.strip() or None

	@field_validator("metadata")
	@classmethod
	def _validate_metadata(cls, metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
		return metadata or None

	@field_validator("improvement_flag")
	@classmethod
	def _normalize_improvement(cls, value: Optional[bool]) -> Optional[bool]:
		return bool(value) if value is not None else None


class MoodEntryOut(BaseModel):
	id: int
	mood_value: int
	mood_label: str
	note: Optional[str] = None
	improvement_flag: Optional[bool] = None
	created_at: datetime
	metadata: Optional[Dict[str, Any]] = None


class MoodEntryListResponse(BaseModel):
	items: List[MoodEntryOut]
	next_offset: Optional[int] = None


class MoodEntryFilterParams(BaseModel):
	limit: int = Field(default=30, ge=1, le=100)
	offset: int = Field(default=0, ge=0)
	from_date: Optional[datetime] = Field(default=None, validation_alias="from", serialization_alias="from")
	to_date: Optional[datetime] = Field(default=None, validation_alias="to", serialization_alias="to")
	mood_min: Optional[int] = Field(default=None, ge=0, le=5)
	mood_max: Optional[int] = Field(default=None, ge=0, le=5)
	improvement: Optional[bool] = None
	order: Literal["asc", "desc"] = "desc"

	model_config = {"populate_by_name": True}


class MoodEntryRecentParams(BaseModel):
	limit: int = Field(default=14, ge=1, le=60)
	order: Literal["asc", "desc"] = "desc"


class MoodDailyStat(BaseModel):
	day: date
	avg_mood_value: Optional[float] = None
	mood_swing: Optional[float] = None
	entries: int


class MoodDailyStatsResponse(BaseModel):
	items: List[MoodDailyStat]


class MoodDistributionResponse(BaseModel):
	range: str
	counts: Dict[str, int]


class MoodTrend(BaseModel):
	direction: Literal["up", "down", "flat"]
	slope: float
	delta_vs_prev_period: Optional[float] = None


class MoodSummaryCurrent(BaseModel):
	mood_value: Optional[int] = None
	mood_label: Optional[str] = None
	created_at: Optional[datetime] = None


class MoodSummaryResponse(BaseModel):
	range: str
	current: MoodSummaryCurrent
	trend: Optional[MoodTrend] = None
	distribution: Dict[str, int]
	avg_mood: Optional[float] = None
	mood_swing: Optional[float] = None
	improvement_entries: int = 0


class MoodFilterResponse(BaseModel):
	filters: Dict[str, Any]
	items: List[MoodEntryOut]


class MoodSuggestionUpdate(BaseModel):
	status: Literal["new", "acknowledged", "dismissed", "completed"]


class MoodSuggestionOut(BaseModel):
	id: int
	suggestion_type: str
	title: str
	description: Optional[str] = None
	tags: Optional[List[str]] = None
	priority: int = Field(default=3, ge=1, le=5)
	status: str
	resolved_at: Optional[datetime] = None
	metadata: Optional[Dict[str, Any]] = None
	created_at: datetime
	updated_at: Optional[datetime] = None


class MoodSuggestionsListResponse(BaseModel):
	items: List[MoodSuggestionOut]
	next_offset: Optional[int] = None


__all__ = [
	"MOOD_VALUE_LABELS",
	"mood_label_for",
	"MoodEntryCreate",
	"MoodEntryUpdate",
	"MoodEntryOut",
	"MoodEntryListResponse",
	"MoodEntryFilterParams",
	"MoodEntryRecentParams",
	"MoodDailyStat",
	"MoodDailyStatsResponse",
	"MoodDistributionResponse",
	"MoodSummaryResponse",
	"MoodFilterResponse",
	"MoodSuggestionUpdate",
	"MoodSuggestionOut",
	"MoodSuggestionsListResponse",
]
