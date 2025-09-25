"""Sleep quality API routes."""

from __future__ import annotations

from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import get_user_by_token
from schemas.sleep import (
	SleepActivateRequest,
	SleepScheduleCreate,
	SleepScheduleUpdate,
	SleepSessionStart,
	SleepStagePatch,
	SleepSessionComplete,
)
from services import sleep_service


router = APIRouter(prefix="/sleep", tags=["sleep"])
bearer_scheme = HTTPBearer(auto_error=False)


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
	schedule = await sleep_service.get_active_schedule(current_user["id"])
	return {"schedule": schedule}


@router.post("/schedule", status_code=status.HTTP_201_CREATED)
async def create_schedule(
	payload: SleepScheduleCreate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	schedule = await sleep_service.create_schedule(current_user["id"], payload.model_dump())
	return {"schedule": schedule}


@router.patch("/schedule/{schedule_id}")
async def update_schedule(
	schedule_id: int,
	payload: SleepScheduleUpdate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	updates = payload.model_dump(exclude_none=True)
	schedule = await sleep_service.update_schedule(current_user["id"], schedule_id, updates)
	if not schedule:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
	return {"schedule": schedule}


@router.patch("/schedule/{schedule_id}/activate")
async def activate_schedule(
	schedule_id: int,
	payload: SleepActivateRequest,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	if not payload.is_active:
		raise HTTPException(status_code=400, detail="is_active must be true to activate")
	schedule = await sleep_service.update_schedule(current_user["id"], schedule_id, {"is_active": True})
	if not schedule:
		raise HTTPException(status_code=404, detail="Schedule not found")
	return {"schedule": schedule}


# --- Sessions ---

@router.post("/sessions/start")
async def start_session(
	payload: SleepSessionStart,
	current_user: dict[str, Any] = Depends(_get_current_user),
):
	result = await sleep_service.start_session(current_user["id"], payload.model_dump(exclude_none=True))
	return result


@router.patch("/sessions/{session_id}/stage")
async def patch_stage(
	session_id: int,
	payload: SleepStagePatch,
	current_user: dict[str, Any] = Depends(_get_current_user),
):
	try:
		await sleep_service.append_stage(current_user["id"], session_id, payload.model_dump())
	except ValueError:
		raise HTTPException(status_code=404, detail="Session not found")
	return {"status": "ok"}


@router.patch("/sessions/{session_id}/complete")
async def patch_complete(
	session_id: int,
	payload: SleepSessionComplete,
	current_user: dict[str, Any] = Depends(_get_current_user),
):
	try:
		result = await sleep_service.complete_session(current_user["id"], session_id, payload.model_dump(exclude_none=True))
	except ValueError:
		raise HTTPException(status_code=404, detail="Session not found")
	return result


@router.get("/sessions/{session_id}")
async def get_session(
	session_id: int,
	include_stages: bool = True,
	current_user: dict[str, Any] = Depends(_get_current_user),
):
	result = await sleep_service.get_session_detail(current_user["id"], session_id, include_stages=include_stages)
	if not result:
		raise HTTPException(status_code=404, detail="Session not found")
	return result


@router.get("/sessions")
async def list_sessions(
	limit: int = Query(20, ge=1, le=100),
	offset: int = Query(0, ge=0),
	from_: datetime | None = Query(None, alias="from"),
	to: datetime | None = None,
	min_duration: float | None = None,
	current_user: dict[str, Any] = Depends(_get_current_user),
):
	filters: dict[str, Any] = {}
	if from_:
		filters["from"] = from_
	if to:
		filters["to"] = to
	if min_duration is not None:
		filters["min_duration"] = min_duration
	return await sleep_service.list_sessions(current_user["id"], limit=limit, offset=offset, filters=filters)


@router.get("/sessions/calendar")
async def sessions_calendar(
	month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
	current_user: dict[str, Any] = Depends(_get_current_user),
):
	return await sleep_service.get_calendar(current_user["id"], month)


@router.get("/sessions/active")
async def get_active_session(current_user: dict[str, Any] = Depends(_get_current_user)):
	return {"session": await sleep_service.get_active_session(current_user["id"]) }

