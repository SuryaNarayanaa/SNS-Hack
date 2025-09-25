from pydantic import BaseModel, Field, validator
from pyparsing import Any
from datetime import datetime

VALID_EXERCISE_TYPES = {"breathing", "mindfulness", "relax", "sleep"}

class MindfulnessGoalOut(BaseModel):
	code: str
	title: str
	short_tagline: str | None = None
	description: str | None = None
	default_exercise_type: str
	recommended_durations: list[int] | None = None
	recommended_soundscape_slugs: list[str] | None = None
	metadata: dict[str, Any] | None = None


class MindfulnessSoundscapeOut(BaseModel):
	id: int
	slug: str
	name: str
	description: str | None = None
	audio_url: str
	loop_seconds: int | None = None
	is_active: bool = True


class SessionCreateRequest(BaseModel):
	exercise_type: str = Field(..., description="breathing | mindfulness | relax | sleep")
	goal_code: str | None = Field(default=None, max_length=64)
	planned_duration_minutes: int = Field(..., gt=0, le=240)
	soundscape_id: int | None = None
	metadata: dict[str, Any] | None = None
	tags: list[str] | None = None

	@validator("exercise_type")
	def validate_exercise_type(cls, value: str) -> str:
		if value not in VALID_EXERCISE_TYPES:
			raise ValueError(f"exercise_type must be one of {sorted(VALID_EXERCISE_TYPES)}")
		return value


class SessionProgressRequest(BaseModel):
	cycles_completed: int | None = Field(default=None, ge=0)
	elapsed_seconds: int | None = Field(default=None, ge=0)
	metadata: dict[str, Any] | None = None


class SessionCompleteRequest(BaseModel):
	cycles_completed: int | None = Field(default=None, ge=0)
	rating_relaxation: int | None = Field(default=None, ge=1, le=10)
	rating_stress_before: int | None = Field(default=None, ge=1, le=10)
	rating_stress_after: int | None = Field(default=None, ge=1, le=10)
	rating_mood_before: int | None = Field(default=None, ge=1, le=10)
	rating_mood_after: int | None = Field(default=None, ge=1, le=10)
	metadata: dict[str, Any] | None = None


class SessionEventRequest(BaseModel):
	event_type: str = Field(..., min_length=1)
	numeric_value: float | None = None
	text_value: str | None = None
	occurred_at: datetime | None = None
	metadata: dict[str, Any] | None = None

