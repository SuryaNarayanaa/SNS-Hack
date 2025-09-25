"""Stress management API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import get_user_by_token
from schemas.stress import (
	StressAssessmentCreate,
	StressExpressionCompleteRequest,
	StressExpressionMetricsBatch,
	StressExpressionMetricsItem,
	StressExpressionStartRequest,
	StressInsightUpdateRequest,
)
from services import stress_service

router = APIRouter(prefix="/stress", tags=["stress management"])
bearer_scheme = HTTPBearer(auto_error=False)


async def _get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> dict[str, Any]:
	if credentials is None:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

	token = credentials.credentials
	user = await get_user_by_token(token)
	if not user:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

	return user | {"token": token}


@router.get("/stressors/catalog")
async def get_stressor_catalog(
	active: bool | None = Query(True, description="Filter by active flag"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await stress_service.list_stressors(active)
	return {"items": items}


@router.post("/assessment", status_code=status.HTTP_201_CREATED)
async def submit_assessment(
	payload: StressAssessmentCreate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	try:
		result = await stress_service.create_assessment(
			current_user["id"],
			payload.score,
			payload.stressor_slugs,
			context_note=payload.context_note,
			expression_session_id=payload.expression_session_id,
			metadata=payload.metadata,
		)
	except ValueError as exc:
		detail = str(exc)
		if detail.startswith("unknown_stressors"):
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown stressor slug supplied") from exc
		if detail == "expression_session_not_found":
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expression session not found") from exc
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
	return result


@router.get("/assessments")
async def list_assessments_endpoint(
	limit: int = Query(30, ge=1, le=100),
	offset: int = Query(0, ge=0),
	from_: datetime | None = Query(None, alias="from"),
	to: datetime | None = None,
	min_score: int | None = Query(None, ge=0, le=5),
	max_score: int | None = Query(None, ge=0, le=5),
	stressor: str | None = Query(None, description="Filter by stressor slug"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	filters: dict[str, Any] = {}
	if from_:
		filters["from"] = from_
	if to:
		filters["to"] = to
	if min_score is not None:
		filters["min_score"] = min_score
	if max_score is not None:
		filters["max_score"] = max_score
	if stressor:
		filters["stressor"] = stressor
	items, next_offset = await stress_service.list_assessments(
		current_user["id"],
		limit=limit,
		offset=offset,
		filters=filters,
	)
	return {"items": items, "next_offset": next_offset}


@router.get("/assessments/recent")
async def list_recent_assessments_endpoint(
	limit: int = Query(10, ge=1, le=50),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await stress_service.list_recent_assessments(current_user["id"], limit)
	return {"items": items}


@router.get("/assessments/{assessment_id}")
async def get_assessment_detail_endpoint(
	assessment_id: int,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	result = await stress_service.get_assessment_detail(current_user["id"], assessment_id)
	if not result:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
	return result


@router.get("/summary/overview")
async def stress_overview(
	range: str | None = Query("30d", description="Range window e.g. 7d, 30d, 90d"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	return await stress_service.get_overview(current_user["id"], range)


@router.get("/stats/daily")
async def stress_daily_stats(
	days: int = Query(30, ge=1, le=180),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await stress_service.get_daily_stats(current_user["id"], days)
	return {"items": items}


@router.get("/stats/stressors")
async def stress_stressor_stats(
	days: int = Query(30, ge=1, le=180),
	limit: int = Query(10, ge=1, le=50),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await stress_service.get_stressor_stats(current_user["id"], days, limit)
	return {"items": items}


@router.post("/expression/start")
async def start_expression_session(
	payload: StressExpressionStartRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	return await stress_service.start_expression_session(
		current_user["id"],
		capture_type=payload.capture_type,
		metadata=payload.metadata,
		device_capabilities=payload.device_capabilities,
	)


@router.patch("/expression/{session_id}/metrics")
async def patch_expression_metrics(
	session_id: int,
	payload: StressExpressionMetricsBatch | StressExpressionMetricsItem,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = payload.items if isinstance(payload, StressExpressionMetricsBatch) else [payload]
	try:
		accepted = await stress_service.append_expression_metrics(current_user["id"], session_id, [item.model_dump(exclude_none=True) for item in items])
	except ValueError as exc:
		if str(exc) == "session_not_found":
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc
		raise
	return {"status": "ok", "accepted": accepted}


@router.patch("/expression/{session_id}/complete")
async def complete_expression_session_endpoint(
	session_id: int,
	payload: StressExpressionCompleteRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	result = await stress_service.complete_expression_session(
		current_user["id"],
		session_id,
		metadata=payload.metadata,
	)
	if not result:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
	return result


@router.get("/expression/{session_id}")
async def get_expression_session_endpoint(
	session_id: int,
	include_metrics: bool = Query(False),
	metrics_limit: int = Query(100, ge=1, le=500),
	metrics_offset: int = Query(0, ge=0),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	result = await stress_service.get_expression_session(
		current_user["id"],
		session_id,
		include_metrics=include_metrics,
		limit=metrics_limit,
		offset=metrics_offset,
	)
	if not result:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
	return result


@router.get("/insights")
async def list_insights_endpoint(
	status_filter: list[str] | None = Query(None, alias="status"),
	type_filter: list[str] | None = Query(None, alias="type"),
	days: int | None = Query(None, ge=1, le=365),
	limit: int = Query(20, ge=1, le=100),
	offset: int = Query(0, ge=0),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items, next_offset = await stress_service.list_insights(
		current_user["id"],
		statuses=status_filter,
		insight_types=type_filter,
		days=days,
		limit=limit,
		offset=offset,
	)
	return {"items": items, "next_offset": next_offset}


@router.patch("/insights/{insight_id}")
async def update_insight_endpoint(
	insight_id: int,
	payload: StressInsightUpdateRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	updated = await stress_service.update_insight_status(current_user["id"], insight_id, payload.status)
	if not updated:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
	return updated


__all__ = ["router"]
