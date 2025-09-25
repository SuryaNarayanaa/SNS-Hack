from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import mood_routes


AUTH_HEADERS = {"Authorization": "Bearer token"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
	async def _fake_get_user(token: str) -> dict[str, object]:
		assert token == "token"
		return {"id": 7, "email": "mood@example.com"}

	monkeypatch.setattr(mood_routes, "get_user_by_token", _fake_get_user)

	app = FastAPI()
	app.include_router(mood_routes.router)
	return TestClient(app)


def test_auth_required(client: TestClient) -> None:
	response = client.get("/mood/entries")
	assert response.status_code == 401
	assert response.json()["detail"] == "Authorization header missing"


def test_create_mood_entry(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	captured: dict[str, object] = {}

	async def _fake_create_entry(user_id: int, payload: dict[str, object]) -> dict[str, object]:
		captured["user_id"] = user_id
		captured["payload"] = payload
		return {"id": 1, "mood_value": 3, "mood_label": "happy", "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc)}

	monkeypatch.setattr(mood_routes.mood_tracker_service, "create_mood_entry", _fake_create_entry)

	response = client.post(
		"/mood/entries",
		headers=AUTH_HEADERS,
		json={"mood_value": 3, "note": "Feeling good"},
	)

	assert response.status_code == 201
	assert captured["user_id"] == 7
	assert captured["payload"]["mood_value"] == 3
	assert response.json()["entry"]["mood_label"] == "happy"


def test_list_entries(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	captured: dict[str, object] = {}

	class _Result:
		def __init__(self) -> None:
			self.items = [{"id": 10, "mood_value": 2, "mood_label": "neutral", "created_at": datetime.now(timezone.utc)}]
			self.next_offset = 15

	async def _fake_list_entries(user_id: int, *, limit: int, offset: int, filters: dict[str, object]):
		captured["user_id"] = user_id
		captured["limit"] = limit
		captured["offset"] = offset
		captured["filters"] = filters
		return _Result()

	monkeypatch.setattr(mood_routes.mood_tracker_service, "list_mood_entries", _fake_list_entries)

	response = client.get(
		"/mood/entries",
		headers=AUTH_HEADERS,
		params={
			"limit": 15,
			"offset": 0,
			"from": "2025-01-01T00:00:00Z",
			"mood_min": 1,
			"order": "asc",
		},
	)

	assert response.status_code == 200
	data = response.json()
	assert data["next_offset"] == 15
	assert captured["limit"] == 15
	assert captured["filters"]["mood_min"] == 1
	start_key = "from" if "from" in captured["filters"] else "from_date"
	assert start_key in captured["filters"]
	assert isinstance(captured["filters"][start_key], datetime)


def test_get_entry_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_get_entry(*args, **kwargs):
		return None

	monkeypatch.setattr(mood_routes.mood_tracker_service, "get_mood_entry", _fake_get_entry)

	response = client.get("/mood/entries/999", headers=AUTH_HEADERS)

	assert response.status_code == 404
	assert response.json()["detail"] == "Entry not found"


def test_update_entry_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_update_entry(user_id: int, entry_id: int, updates: dict[str, object]) -> dict[str, object] | None:
		assert user_id == 7
		assert entry_id == 12
		assert updates == {"note": "Updated"}
		return {"id": entry_id, "mood_value": 4, "mood_label": "joyful", "created_at": datetime.now(timezone.utc)}

	monkeypatch.setattr(mood_routes.mood_tracker_service, "update_mood_entry", _fake_update_entry)

	response = client.patch(
		"/mood/entries/12",
		headers=AUTH_HEADERS,
		json={"note": "Updated"},
	)

	assert response.status_code == 200
	assert response.json()["entry"]["mood_label"] == "joyful"


def test_delete_entry_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_delete_entry(*args, **kwargs):
		return False

	monkeypatch.setattr(mood_routes.mood_tracker_service, "delete_mood_entry", _fake_delete_entry)

	response = client.delete("/mood/entries/5", headers=AUTH_HEADERS)

	assert response.status_code == 404
	assert response.json()["detail"] == "Entry not found"


def test_summary_overview(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_summary(user_id: int, range_value: str | None) -> dict[str, object]:
		assert range_value == "30d"
		return {"range": "30d", "avg_mood": 3.2}

	monkeypatch.setattr(mood_routes.mood_tracker_service, "get_summary_overview", _fake_summary)

	response = client.get("/mood/summary/overview", headers=AUTH_HEADERS)

	assert response.status_code == 200
	assert response.json()["avg_mood"] == 3.2


def test_list_suggestions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	captured: dict[str, object] = {}

	class _Result:
		def __init__(self) -> None:
			self.items = [{"id": 2, "status": "new"}]
			self.next_offset = None

	async def _fake_list_suggestions(user_id: int, *, statuses, suggestion_types, days, limit, offset):
		captured.update(
			{
				"user_id": user_id,
				"statuses": statuses,
				"types": suggestion_types,
				"days": days,
				"limit": limit,
				"offset": offset,
			}
		)
		return _Result()

	monkeypatch.setattr(mood_routes.mood_tracker_service, "list_suggestions", _fake_list_suggestions)

	response = client.get(
		"/mood/suggestions",
		headers=AUTH_HEADERS,
		params={"status": ["new"], "type": ["positive_activity"], "days": 14},
	)

	assert response.status_code == 200
	assert captured["statuses"] == ["new"]
	assert captured["types"] == ["positive_activity"]
	assert response.json()["items"][0]["id"] == 2


def test_update_suggestion_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_update(*args, **kwargs):
		return None

	monkeypatch.setattr(mood_routes.mood_tracker_service, "update_suggestion_status", _fake_update)

	response = client.patch(
		"/mood/suggestions/3",
		headers=AUTH_HEADERS,
		json={"status": "acknowledged"},
	)

	assert response.status_code == 404
	assert response.json()["detail"] == "Suggestion not found"


def test_list_active_suggestions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
	async def _fake_active(user_id: int, limit: int):
		assert limit == 10
		return [{"id": 8, "status": "new"}]

	monkeypatch.setattr(mood_routes.mood_tracker_service, "list_active_suggestions", _fake_active)

	response = client.get("/mood/suggestions/active", headers=AUTH_HEADERS, params={"limit": 10})

	assert response.status_code == 200
	assert response.json()["items"][0]["id"] == 8
