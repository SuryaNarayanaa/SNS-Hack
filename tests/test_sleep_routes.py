from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import sleep_routes


AUTH_HEADERS = {"Authorization": "Bearer token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
	async def _fake_get_user(token: str) -> dict[str, object]:
		assert token == "token"
		return {"id": 1, "email": "user@example.com"}

	monkeypatch.setattr(sleep_routes, "get_user_by_token", _fake_get_user)

	app = FastAPI()
	app.include_router(sleep_routes.router)
	return TestClient(app)


def test_auth_required(client: TestClient) -> None:
	response = client.get("/sleep/schedule")
	assert response.status_code == 401
	assert response.json()["detail"] == "Authorization header missing"


def test_get_active_schedule(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_get_active_schedule(user_id: int) -> dict[str, object] | None:
		assert user_id == 1
		return {"id": 10, "timezone": "UTC"}

	monkeypatch.setattr(sleep_routes.sleep_service, "get_active_schedule", _fake_get_active_schedule)

	response = client.get("/sleep/schedule", headers=AUTH_HEADERS)
	assert response.status_code == 200
	assert response.json() == {"schedule": {"id": 10, "timezone": "UTC"}}


def test_create_schedule(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	captured: dict[str, object] = {}

	async def _fake_create_schedule(user_id: int, payload: dict[str, object]) -> dict[str, object]:
		assert user_id == 1
		captured.update(payload)
		return {"id": 11, **payload}

	monkeypatch.setattr(sleep_routes.sleep_service, "create_schedule", _fake_create_schedule)

	response = client.post(
		"/sleep/schedule",
		headers=AUTH_HEADERS,
		json={
			"bedtime_local": "22:30:00",
			"wake_time_local": "07:00:00",
			"timezone": "UTC",
			"active_days": [0, 1, 2],
			"target_duration_minutes": 480,
			"auto_set_alarm": True,
			"show_stats_auto": False,
			"metadata": {"note": "test"},
		},
	)

	assert response.status_code == 201
	data = response.json()["schedule"]
	assert data["id"] == 11
	assert captured["timezone"] == "UTC"
	assert captured["active_days"] == [0, 1, 2]


def test_update_schedule_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_update_schedule(user_id: int, schedule_id: int, updates: dict[str, object]) -> dict[str, object] | None:
		assert (user_id, schedule_id) == (1, 44)
		assert updates == {"timezone": "Asia/Tokyo"}
		return {"id": schedule_id, "timezone": "Asia/Tokyo"}

	monkeypatch.setattr(sleep_routes.sleep_service, "update_schedule", _fake_update_schedule)

	response = client.patch(
		"/sleep/schedule/44",
		headers=AUTH_HEADERS,
		json={"timezone": "Asia/Tokyo"},
	)

	assert response.status_code == 200
	assert response.json()["schedule"]["timezone"] == "Asia/Tokyo"


def test_update_schedule_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_update_schedule(*args, **kwargs):
		return None

	monkeypatch.setattr(sleep_routes.sleep_service, "update_schedule", _fake_update_schedule)

	response = client.patch(
		"/sleep/schedule/99",
		headers=AUTH_HEADERS,
		json={"timezone": "UTC"},
	)

	assert response.status_code == 404
	assert response.json()["detail"] == "Schedule not found"


def test_activate_schedule_requires_true(client: TestClient) -> None:
	response = client.patch(
		"/sleep/schedule/1/activate",
		headers=AUTH_HEADERS,
		json={"is_active": False},
	)
	assert response.status_code == 400
	assert response.json()["detail"] == "is_active must be true to activate"


def test_activate_schedule_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_activate(user_id: int, schedule_id: int, updates: dict[str, object]) -> dict[str, object] | None:
		assert updates == {"is_active": True}
		return {"id": schedule_id, "is_active": True}

	monkeypatch.setattr(sleep_routes.sleep_service, "update_schedule", _fake_activate)

	response = client.patch(
		"/sleep/schedule/3/activate",
		headers=AUTH_HEADERS,
		json={"is_active": True},
	)

	assert response.status_code == 200
	assert response.json()["schedule"]["is_active"] is True


def test_start_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_start_session(user_id: int, payload: dict[str, object]) -> dict[str, object]:
		assert payload["schedule_id"] == 5
		return {"id": 77, "status": "in_progress"}

	monkeypatch.setattr(sleep_routes.sleep_service, "start_session", _fake_start_session)

	response = client.post(
		"/sleep/sessions/start",
		headers=AUTH_HEADERS,
		json={"schedule_id": 5},
	)

	assert response.status_code == 200
	assert response.json()["status"] == "in_progress"


def test_patch_stage_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	called: dict[str, object] = {}

	async def _fake_append_stage(user_id: int, session_id: int, payload: dict[str, object]) -> None:
		called.update({"user_id": user_id, "session_id": session_id, "payload": payload})

	monkeypatch.setattr(sleep_routes.sleep_service, "append_stage", _fake_append_stage)

	response = client.patch(
		"/sleep/sessions/9/stage",
		headers=AUTH_HEADERS,
		json={
			"stage": "deep",
			"start_at": "2025-01-01T00:00:00Z",
			"end_at": "2025-01-01T00:30:00Z",
		},
	)

	assert response.status_code == 200
	assert response.json() == {"status": "ok"}
	assert called["session_id"] == 9
	assert called["payload"]["stage"] == "deep"


def test_patch_stage_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_append_stage(*args, **kwargs):
		raise ValueError("missing")

	monkeypatch.setattr(sleep_routes.sleep_service, "append_stage", _fake_append_stage)

	response = client.patch(
		"/sleep/sessions/9/stage",
		headers=AUTH_HEADERS,
		json={
			"stage": "light",
			"start_at": "2025-01-01T00:00:00Z",
			"end_at": "2025-01-01T00:30:00Z",
		},
	)

	assert response.status_code == 404
	assert response.json()["detail"] == "Session not found"


def test_complete_session_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_complete(user_id: int, session_id: int, payload: dict[str, object]) -> dict[str, object]:
		assert isinstance(payload["end_at"], datetime)
		return {"id": session_id, "quality_label": "good"}

	monkeypatch.setattr(sleep_routes.sleep_service, "complete_session", _fake_complete)

	response = client.patch(
		"/sleep/sessions/12/complete",
		headers=AUTH_HEADERS,
		json={"end_at": "2025-01-01T07:00:00+00:00"},
	)

	assert response.status_code == 200
	assert response.json()["quality_label"] == "good"


def test_complete_session_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_complete(*args, **kwargs):
		raise ValueError("nope")

	monkeypatch.setattr(sleep_routes.sleep_service, "complete_session", _fake_complete)

	response = client.patch(
		"/sleep/sessions/12/complete",
		headers=AUTH_HEADERS,
		json={"end_at": "2025-01-01T07:00:00+00:00"},
	)

	assert response.status_code == 404
	assert response.json()["detail"] == "Session not found"


def test_get_session_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_get_session(user_id: int, session_id: int, include_stages: bool) -> dict[str, object] | None:
		assert include_stages is False
		return {"id": session_id, "start_at": "2025-01-01T00:00:00Z"}

	monkeypatch.setattr(sleep_routes.sleep_service, "get_session_detail", _fake_get_session)

	response = client.get(
		"/sleep/sessions/88",
		headers=AUTH_HEADERS,
		params={"include_stages": False},
	)

	assert response.status_code == 200
	assert response.json()["id"] == 88


def test_get_session_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_get_session(*args, **kwargs):
		return None

	monkeypatch.setattr(sleep_routes.sleep_service, "get_session_detail", _fake_get_session)

	response = client.get("/sleep/sessions/42", headers=AUTH_HEADERS)
	assert response.status_code == 404
	assert response.json()["detail"] == "Session not found"


def test_list_sessions_with_filters(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	captured_filters: dict[str, object] = {}

	async def _fake_list_sessions(user_id: int, *, limit: int, offset: int, filters: dict[str, object]):
		captured_filters.update(filters)
		assert limit == 10
		assert offset == 5
		return {"items": [{"id": 1}], "next_offset": None}

	monkeypatch.setattr(sleep_routes.sleep_service, "list_sessions", _fake_list_sessions)

	response = client.get(
		"/sleep/sessions",
		headers=AUTH_HEADERS,
		params={
			"limit": 10,
			"offset": 5,
			"from": "2025-01-01T00:00:00Z",
			"to": "2025-01-31T00:00:00Z",
			"min_duration": 45,
		},
	)

	assert response.status_code == 200
	assert response.json()["items"][0]["id"] == 1
	assert isinstance(captured_filters["from"], datetime)
	assert isinstance(captured_filters["to"], datetime)
	assert captured_filters["min_duration"] == 45


def test_sessions_calendar(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_calendar(user_id: int, month: str | None) -> dict[str, object]:
		assert month == "2025-01"
		return {"month": month, "days": []}

	monkeypatch.setattr(sleep_routes.sleep_service, "get_calendar", _fake_calendar)

	response = client.get("/sleep/sessions/calendar", headers=AUTH_HEADERS, params={"month": "2025-01"})

	assert response.status_code == 200
	assert response.json()["month"] == "2025-01"


def test_get_active_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_get_active_session(user_id: int) -> dict[str, object] | None:
		return {"id": 101, "status": "in_progress"}

	monkeypatch.setattr(sleep_routes.sleep_service, "get_active_session", _fake_get_active_session)

	response = client.get("/sleep/sessions/active", headers=AUTH_HEADERS)

	assert response.status_code == 200
	assert response.json()["session"]["id"] == 101
