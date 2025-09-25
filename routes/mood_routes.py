"""Mood tracker API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import get_user_by_token
from schemas.mood_tracker_schema import (
	MoodEntryCreate,
	MoodEntryFilterParams,
	MoodEntryRecentParams,
	MoodEntryUpdate,
	MoodSuggestionUpdate,
)
from services import mood_tracker_service


router = APIRouter(prefix="/mood", tags=["mood tracker"])
bearer_scheme = HTTPBearer(auto_error=False)


async def _get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> dict[str, Any]:
	if credentials is None:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

	token = credentials.credentials
	user = await get_user_by_token(token)
	if not user:
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

	return user | {"token": token}


@router.post("/entries", status_code=status.HTTP_201_CREATED)
async def create_mood_entry(
	payload: MoodEntryCreate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	entry = await mood_tracker_service.create_mood_entry(current_user["id"], payload.model_dump())
	return {"entry": entry}


@router.get("/entries")
async def list_mood_entries(
	filters: MoodEntryFilterParams = Depends(),
	from_override: datetime | None = Query(None, alias="from"),
	to_override: datetime | None = Query(None, alias="to"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	raw_filters = filters.model_dump(exclude_none=True)
	limit = raw_filters.pop("limit", filters.limit)
	offset = raw_filters.pop("offset", filters.offset)
	from_date = raw_filters.pop("from_date", None)
	to_date = raw_filters.pop("to_date", None)
	if from_override is not None:
		raw_filters["from"] = from_override
	elif from_date is not None:
		raw_filters["from"] = from_date
	if to_override is not None:
		raw_filters["to"] = to_override
	elif to_date is not None:
		raw_filters["to"] = to_date
	result = await mood_tracker_service.list_mood_entries(
		current_user["id"],
		limit=limit,
		offset=offset,
		filters=raw_filters,
	)
	return {"items": result.items, "next_offset": result.next_offset}


@router.get("/entries/recent")
async def list_recent_entries(
	params: MoodEntryRecentParams = Depends(),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await mood_tracker_service.list_recent_entries(
		current_user["id"],
		limit=params.limit,
		order=params.order,
	)
	return {"items": items}


@router.get("/entries/{entry_id}")
async def get_mood_entry(
	entry_id: int,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	entry = await mood_tracker_service.get_mood_entry(current_user["id"], entry_id)
	if not entry:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
	return {"entry": entry}


@router.patch("/entries/{entry_id}")
async def update_mood_entry(
	entry_id: int,
	payload: MoodEntryUpdate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	updates = payload.model_dump(exclude_none=True)
	entry = await mood_tracker_service.update_mood_entry(current_user["id"], entry_id, updates)
	if not entry:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
	return {"entry": entry}


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mood_entry(
	entry_id: int,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> None:
	deleted = await mood_tracker_service.delete_mood_entry(current_user["id"], entry_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")


@router.get("/summary/overview")
async def get_mood_summary(
	range: str | None = Query("30d", description="Range window e.g. 7d, 30d, 90d, all"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	return await mood_tracker_service.get_summary_overview(current_user["id"], range)


@router.get("/stats/daily")
async def get_daily_stats(
	days: int = Query(30, ge=1, le=365),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await mood_tracker_service.get_daily_stats(current_user["id"], days)
	return {"items": items}


@router.get("/stats/distribution")
async def get_distribution(
	range: str | None = Query("30d", description="Range window e.g. 7d, 30d, all"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	return await mood_tracker_service.get_distribution(current_user["id"], range)


@router.get("/entries/filter")
async def filter_mood_entries(
	filters: MoodEntryFilterParams = Depends(),
	from_override: datetime | None = Query(None, alias="from"),
	to_override: datetime | None = Query(None, alias="to"),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	raw_filters = filters.model_dump(exclude_none=True)
	limit = raw_filters.pop("limit", filters.limit)
	offset = raw_filters.pop("offset", filters.offset)
	from_date = raw_filters.pop("from_date", None)
	to_date = raw_filters.pop("to_date", None)
	if from_override is not None:
		raw_filters["from"] = from_override
	elif from_date is not None:
		raw_filters["from"] = from_date
	if to_override is not None:
		raw_filters["to"] = to_override
	elif to_date is not None:
		raw_filters["to"] = to_date
	return await mood_tracker_service.filter_entries(
		current_user["id"],
		limit=limit,
		offset=offset,
		filters=raw_filters,
	)


@router.get("/suggestions")
async def list_suggestions(
	status_filter: list[str] | None = Query(None, alias="status"),
	type_filter: list[str] | None = Query(None, alias="type"),
	days: int | None = Query(None, ge=1, le=365),
	limit: int = Query(20, ge=1, le=100),
	offset: int = Query(0, ge=0),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	result = await mood_tracker_service.list_suggestions(
		current_user["id"],
		statuses=status_filter,
		suggestion_types=type_filter,
		days=days,
		limit=limit,
		offset=offset,
	)
	return {"items": result.items, "next_offset": result.next_offset}


@router.patch("/suggestions/{suggestion_id}")
async def update_suggestion(
	suggestion_id: int,
	payload: MoodSuggestionUpdate,
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	updated = await mood_tracker_service.update_suggestion_status(
		current_user["id"],
		suggestion_id,
		payload.status,
	)
	if not updated:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
	return {"suggestion": updated}


@router.get("/suggestions/active")
async def list_active_suggestions(
	limit: int = Query(20, ge=1, le=100),
	current_user: dict[str, Any] = Depends(_get_current_user),
) -> dict[str, Any]:
	items = await mood_tracker_service.list_active_suggestions(current_user["id"], limit=limit)
	return {"items": items}


__all__ = ["router"]
