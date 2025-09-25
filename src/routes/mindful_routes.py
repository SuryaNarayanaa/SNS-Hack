"""Mindful Hours API endpoints and response models."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import get_user_by_token
from services.mindful_service import (
	append_mindfulness_session_event,
	complete_mindfulness_session,
	create_mindfulness_session,
	get_active_mindfulness_session,
	get_mindful_daily_minutes,
	get_mindful_stats_overview,
	get_mindfulness_session,
	list_mindfulness_goals,
	list_mindfulness_session_events,
	list_mindfulness_soundscapes,
	query_mindfulness_sessions,
	update_mindfulness_session_progress,
)

from schemas.mindful_schemas import (
	VALID_EXERCISE_TYPES,
	MindfulnessGoalOut,
	MindfulnessSoundscapeOut,
	SessionCompleteRequest,
	SessionCreateRequest,
	SessionEventRequest,
	SessionProgressRequest,
)

router = APIRouter(prefix="/mindful", tags=["Mindful Hours"])

bearer_scheme = HTTPBearer(auto_error=False)

async def _get_current_user(
	credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
	if credentials is None:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

	token = credentials.credentials
	user = await get_user_by_token(token)
	if not user:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

	return {**user, "token": token}


def _serialize_goal(row: dict[str, Any]) -> MindfulnessGoalOut:
	payload = {
		"code": row.get("code"),
		"title": row.get("title"),
		"short_tagline": row.get("short_tagline"),
		"description": row.get("description"),
		"default_exercise_type": row.get("default_exercise_type"),
		"recommended_durations": row.get("recommended_durations"),
		"recommended_soundscape_slugs": row.get("recommended_soundscape_slugs"),
		"metadata": row.get("metadata"),
	}
	return MindfulnessGoalOut(**payload)


def _serialize_soundscape(row: dict[str, Any]) -> MindfulnessSoundscapeOut:
	payload = {
		"id": row.get("id"),
		"slug": row.get("slug"),
		"name": row.get("name"),
		"description": row.get("description"),
		"audio_url": row.get("audio_url"),
		"loop_seconds": row.get("loop_seconds"),
		"is_active": row.get("is_active", True),
	}
	return MindfulnessSoundscapeOut(**payload)


def _serialize_session(row: dict[str, Any]) -> dict[str, Any]:
	session = dict(row)
	session.pop("user_id", None)
	status_value = "completed" if session.get("end_at") else "in_progress"
	session["status"] = status_value
	for key in ("score_restful", "score_focus"):
		if session.get(key) is not None:
			session[key] = float(session[key])
	planned = session.get("planned_duration_seconds")
	session["planned_duration_minutes"] = round(planned / 60.0, 2) if planned else None
	actual = session.get("actual_duration_seconds")
	session["actual_minutes"] = round(actual / 60.0, 2) if actual else None
	session["tags"] = list(session.get("tags") or [])
	if session.get("metadata") is None:
		session["metadata"] = {}
	return jsonable_encoder(session)


@router.get("/catalog/goals")
async def get_mindfulness_goals(
	exercise_type: str | None = Query(default=None, description="Optional filter by default exercise type"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	rows = await list_mindfulness_goals(exercise_type)
	items = [_serialize_goal(row).dict() for row in rows]
	return {"items": items}


@router.get("/catalog/soundscapes")
async def get_mindfulness_soundscapes(
	active: bool | None = Query(default=True, description="Filter active soundscapes"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	rows = await list_mindfulness_soundscapes(active)
	items = [_serialize_soundscape(row).dict() for row in rows]
	return {"items": items}


@router.post("/sessions")
async def start_mindfulness_session(
	payload: SessionCreateRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	session = await create_mindfulness_session(
		current_user["id"],
		exercise_type=payload.exercise_type,
		planned_duration_minutes=payload.planned_duration_minutes,
		goal_code=payload.goal_code,
		soundscape_id=payload.soundscape_id,
		metadata=payload.metadata,
		tags=payload.tags,
	)
	if not session:
		raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create session")
	return _serialize_session(session)


@router.get("/sessions")
async def list_mindfulness_sessions_endpoint(
	limit: int = Query(20, ge=1, le=100),
	offset: int = Query(0, ge=0),
	exercise_type: str | None = Query(default=None),
	goal_code: str | None = Query(default=None),
	range: str | None = Query(default=None, description="Range window e.g. 30d, 90d, 1y"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	if exercise_type and exercise_type not in VALID_EXERCISE_TYPES:
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid exercise_type filter")

	rows, next_offset = await query_mindfulness_sessions(
		current_user["id"],
		limit=limit,
		offset=offset,
		exercise_type=exercise_type,
		goal_code=goal_code,
		date_range=range,
	)
	items = [_serialize_session(row) for row in rows]
	return {"items": items, "next_offset": next_offset}


@router.get("/sessions/active")
async def get_active_mindfulness_session_endpoint(
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	session = await get_active_mindfulness_session(current_user["id"])
	return {"session": _serialize_session(session) if session else None}


@router.get("/sessions/{session_id}")
async def get_mindfulness_session_detail(
	session_id: int,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	session = await get_mindfulness_session(session_id, current_user["id"])
	if not session:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
	return _serialize_session(session)


@router.patch("/sessions/{session_id}/progress")
async def update_mindfulness_progress(
	session_id: int,
	payload: SessionProgressRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	session = await update_mindfulness_session_progress(
		session_id,
		current_user["id"],
		cycles_completed=payload.cycles_completed,
		elapsed_seconds=payload.elapsed_seconds,
		metadata=payload.metadata,
	)
	if not session:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or already completed")
	return {"status": "ok", "session": _serialize_session(session)}


@router.patch("/sessions/{session_id}/complete")
async def complete_mindfulness_session_endpoint(
	session_id: int,
	payload: SessionCompleteRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	session = await complete_mindfulness_session(
		session_id,
		current_user["id"],
		cycles_completed=payload.cycles_completed,
		rating_relaxation=payload.rating_relaxation,
		rating_stress_before=payload.rating_stress_before,
		rating_stress_after=payload.rating_stress_after,
		rating_mood_before=payload.rating_mood_before,
		rating_mood_after=payload.rating_mood_after,
		metadata=payload.metadata,
	)
	if not session:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
	return _serialize_session(session)


@router.get("/sessions/{session_id}/events")
async def get_mindfulness_session_events(
	session_id: int,
	limit: int = Query(200, ge=1, le=1000),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	events = await list_mindfulness_session_events(session_id, current_user["id"], limit=limit)
	return {"items": jsonable_encoder(events)}


@router.post("/sessions/{session_id}/events")
async def add_mindfulness_session_event(
	session_id: int,
	payload: SessionEventRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	session = await get_mindfulness_session(session_id, current_user["id"])
	if not session:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

	event = await append_mindfulness_session_event(
		session_id,
		current_user["id"],
		payload.event_type,
		numeric_value=payload.numeric_value,
		text_value=payload.text_value,
		occurred_at=payload.occurred_at,
		metadata=payload.metadata,
	)
	return jsonable_encoder(event)


@router.get("/stats/overview")
async def get_mindfulness_stats_overview_endpoint(
	range: str | None = Query(default="30d", description="Range window e.g. 7d, 30d, 90d, 1y"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	overview = await get_mindful_stats_overview(current_user["id"], range)
	return jsonable_encoder(overview)


@router.get("/stats/daily")
async def get_mindfulness_stats_daily(
	days: int = Query(30, ge=1, le=180),
	exercise_type: str | None = Query(default=None),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	if exercise_type and exercise_type not in VALID_EXERCISE_TYPES:
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid exercise_type filter")
	items = await get_mindful_daily_minutes(current_user["id"], days=days, exercise_type=exercise_type)
	return {"items": jsonable_encoder(items)}

def _auto_attach_router() -> None:
	try:
		from fastapi import FastAPI
	except Exception:
		return

	if getattr(FastAPI, "_mindful_routes_patched", False):  # type: ignore[attr-defined]
		return

	original_init = FastAPI.__init__

	def _patched_init(self, *args, **kwargs):  # type: ignore[no-redef]
		original_init(self, *args, **kwargs)
		if not getattr(self.state, "_mindful_routes_attached", False):
			self.include_router(router)
			setattr(self.state, "_mindful_routes_attached", True)

	FastAPI.__init__ = _patched_init  # type: ignore[assignment]
	setattr(FastAPI, "_mindful_routes_patched", True)


_auto_attach_router()


__all__ = ["router"]
