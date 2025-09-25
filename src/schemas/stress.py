from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


StressDirection = Literal["up", "down", "flat"]


class StressStressorOut(BaseModel):
	id: int
	slug: str
	name: str
	description: str | None = None
	is_active: bool = True
	metadata: dict[str, Any] | None = None


class StressAssessmentStressorOut(BaseModel):
	id: int
	slug: str
	name: str | None = None
	impact_level: str | None = None
	impact_score: float | None = None
	metadata: dict[str, Any] | None = None


class StressAssessmentCreate(BaseModel):
	score: int = Field(..., ge=0, le=5)
	stressor_slugs: list[str] = Field(default_factory=list)
	context_note: str | None = Field(default=None, max_length=2000)
	expression_session_id: int | None = None
	metadata: dict[str, Any] | None = None

	@field_validator("stressor_slugs")
	@classmethod
	def ensure_unique_slugs(cls, value: list[str]) -> list[str]:
		unique: list[str] = []
		seen: set[str] = set()
		for slug in value:
			slug_norm = slug.strip().lower()
			if slug_norm and slug_norm not in seen:
				unique.append(slug_norm)
				seen.add(slug_norm)
		return unique


class StressAssessmentBase(BaseModel):
	id: int
	score: int
	qualitative_label: str
	created_at: datetime


class StressAssessmentSummary(StressAssessmentBase):
	context_note: str | None = None


class StressAssessmentDetail(StressAssessmentSummary):
	expression_session_id: int | None = None
	metadata: dict[str, Any] | None = None
	stressors: list[StressAssessmentStressorOut] = Field(default_factory=list)


class StressAssessmentsResponse(BaseModel):
	items: list[StressAssessmentSummary]
	next_offset: int | None = None


class StressRecentAssessmentsResponse(BaseModel):
	items: list[StressAssessmentSummary]


class StressOverviewCurrent(BaseModel):
	score: int
	qualitative_label: str
	created_at: datetime | None = None


class StressTrendInfo(BaseModel):
	direction: StressDirection | None = None
	slope: float | None = None
	delta_vs_prev_period: float | None = None


class StressTopStressor(BaseModel):
	slug: str
	name: str | None = None
	avg_score: float | None = None
	impact_level: str | None = None
	avg_impact_score: float | None = None


class StressOverviewResponse(BaseModel):
	current: StressOverviewCurrent | None = None
	trend: StressTrendInfo | None = None
	top_stressors: list[StressTopStressor] = Field(default_factory=list)
	distribution: dict[str, int] = Field(default_factory=dict)


class StressDailyStat(BaseModel):
	day: date
	avg_score: float | None = None
	assessments: int


class StressDailyStatsResponse(BaseModel):
	items: list[StressDailyStat]


class StressStressorStat(BaseModel):
	slug: str
	name: str | None = None
	assessments: int
	avg_score: float | None = None
	avg_impact_score: float | None = None


class StressStressorStatsResponse(BaseModel):
	items: list[StressStressorStat]


class StressExpressionStartRequest(BaseModel):
	capture_type: str = Field(default="camera")
	metadata: dict[str, Any] | None = None
	device_capabilities: dict[str, Any] | None = None


class StressExpressionSessionOut(BaseModel):
	id: int
	user_id: int
	started_at: datetime
	completed_at: datetime | None = None
	capture_type: str | None = None
	status: str
	metadata: dict[str, Any] | None = None
	device_capabilities: dict[str, Any] | None = None


class StressExpressionMetricsItem(BaseModel):
	captured_at: datetime | None = None
	heart_rate_bpm: float | None = Field(default=None, ge=0)
	systolic_bp: int | None = Field(default=None, ge=0)
	diastolic_bp: int | None = Field(default=None, ge=0)
	breathing_rate: float | None = Field(default=None, ge=0)
	expression_primary: str | None = None
	expression_confidence: float | None = Field(default=None, ge=0, le=1)
	stress_inference: float | None = Field(default=None, ge=0)
	metadata: dict[str, Any] | None = None


class StressExpressionMetricsBatch(BaseModel):
	items: list[StressExpressionMetricsItem]

	@field_validator("items")
	@classmethod
	def ensure_non_empty(cls, value: list[StressExpressionMetricsItem]) -> list[StressExpressionMetricsItem]:
		if not value:
			raise ValueError("items must contain at least one metric payload")
		return value


class StressExpressionCompleteRequest(BaseModel):
	metadata: dict[str, Any] | None = None


class StressExpressionMetricsResponse(BaseModel):
	status: str
	accepted: int


class StressExpressionSessionDetail(StressExpressionSessionOut):
	samples: int | None = None
	avg_heart_rate: float | None = None
	avg_stress_inference: float | None = None
	peak_heart_rate: float | None = None
	metrics: list[StressExpressionMetricsItem] | None = None


class StressInsightOut(BaseModel):
	id: int
	insight_type: str
	severity: str | None = None
	title: str | None = None
	description: str | None = None
	suggested_action: str | None = None
	status: str | None = None
	related_stressor_id: int | None = None
	first_detected_at: datetime | None = None
	last_occurrence_at: datetime | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime
	updated_at: datetime | None = None


class StressInsightsResponse(BaseModel):
	items: list[StressInsightOut]
	next_offset: int | None = None


class StressInsightUpdateRequest(BaseModel):
	status: str = Field(..., min_length=2)
