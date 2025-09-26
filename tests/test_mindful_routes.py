from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes import mindful_routes


AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


def _sample_session_completed() -> dict[str, object]:
    start = datetime(2025, 1, 1, 6, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=45)
    return {
        "id": 101,
        "user_id": 1,
        "exercise_type": "mindfulness",
        "goal_code": "calm",
        "planned_duration_seconds": 2700,
        "actual_duration_seconds": 2400,
        "soundscape_id": 3,
        "start_at": start,
        "end_at": end,
        "score_restful": 92.5,
        "score_focus": 88.0,
        "tags": ["evening"],
        "metadata": {"note": "completed"},
    }


def _sample_session_in_progress() -> dict[str, object]:
    start = datetime(2025, 1, 2, 7, 30, tzinfo=timezone.utc)
    return {
        "id": 202,
        "user_id": 1,
        "exercise_type": "breathing",
        "goal_code": "focus",
        "planned_duration_seconds": 1800,
        "actual_duration_seconds": None,
        "soundscape_id": None,
        "start_at": start,
        "end_at": None,
        "score_restful": None,
        "score_focus": None,
        "tags": [],
        "metadata": None,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _fake_get_user_by_token(token: str) -> dict[str, object]:
        return {"id": 1, "email": "user@example.com", "is_guest": False}

    monkeypatch.setattr(mindful_routes, "get_user_by_token", _fake_get_user_by_token)

    app = FastAPI()
    return TestClient(app)


def test_get_mindfulness_goals(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list_goals(exercise_type: str | None) -> list[dict[str, object]]:
        assert exercise_type is None
        return [
            {
                "code": "calm",
                "title": "Calm Evenings",
                "short_tagline": "Wind down",
                "description": "Relax before bed",
                "default_exercise_type": "mindfulness",
                "recommended_durations": [5, 10],
                "recommended_soundscape_slugs": ["forest"],
                "metadata": {"pillars": ["calm"]},
            }
        ]

    monkeypatch.setattr(mindful_routes, "list_mindfulness_goals", _fake_list_goals)

    response = client.get("/mindful/catalog/goals", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["code"] == "calm"
    assert payload["items"][0]["default_exercise_type"] == "mindfulness"


def test_get_mindfulness_soundscapes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list_soundscapes(active: bool | None) -> list[dict[str, object]]:
        assert active is True
        return [
            {
                "id": 1,
                "slug": "gentle-rain",
                "name": "Gentle Rain",
                "description": "Ambient rain sounds",
                "audio_url": "https://example.com/rain.mp3",
                "loop_seconds": 120,
                "is_active": True,
            }
        ]

    monkeypatch.setattr(mindful_routes, "list_mindfulness_soundscapes", _fake_list_soundscapes)

    response = client.get("/mindful/catalog/soundscapes", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["slug"] == "gentle-rain"


def test_start_mindfulness_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_create_session(user_id: int, **kwargs: object) -> dict[str, object]:
        assert user_id == 1
        return _sample_session_in_progress()

    monkeypatch.setattr(mindful_routes, "create_mindfulness_session", _fake_create_session)

    response = client.post(
        "/mindful/sessions",
        headers=AUTH_HEADERS,
        json={
            "exercise_type": "breathing",
            "planned_duration_minutes": 30,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "in_progress"
    assert payload["exercise_type"] == "breathing"


def test_list_mindfulness_sessions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_query_sessions(user_id: int, **kwargs: object) -> tuple[list[dict[str, object]], int | None]:
        assert user_id == 1
        return ([_sample_session_completed()], 40)

    monkeypatch.setattr(mindful_routes, "query_mindfulness_sessions", _fake_query_sessions)

    response = client.get("/mindful/sessions", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["status"] == "completed"
    assert payload["next_offset"] == 40


def test_get_mindfulness_session_detail(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: int, user_id: int) -> dict[str, object] | None:
        assert session_id == 77
        assert user_id == 1
        return _sample_session_completed()

    monkeypatch.setattr(mindful_routes, "get_mindfulness_session", _fake_get_session)

    response = client.get("/mindful/sessions/77", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 101
    assert payload["status"] == "completed"


def test_update_mindfulness_progress(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_update_progress(session_id: int, user_id: int, **kwargs: object) -> dict[str, object] | None:
        assert session_id == 55
        assert user_id == 1
        return _sample_session_in_progress()

    monkeypatch.setattr(mindful_routes, "update_mindfulness_session_progress", _fake_update_progress)

    response = client.patch(
        "/mindful/sessions/55/progress",
        headers=AUTH_HEADERS,
        json={"cycles_completed": 2, "elapsed_seconds": 120},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["session"]["status"] == "in_progress"


def test_complete_mindfulness_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_complete_session(session_id: int, user_id: int, **kwargs: object) -> dict[str, object] | None:
        assert session_id == 12
        assert user_id == 1
        return _sample_session_completed()

    monkeypatch.setattr(mindful_routes, "complete_mindfulness_session", _fake_complete_session)

    response = client.patch(
        "/mindful/sessions/12/complete",
        headers=AUTH_HEADERS,
        json={"rating_relaxation": 8},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["planned_duration_minutes"] == pytest.approx(45.0)


def test_get_mindfulness_session_events(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list_events(session_id: int, user_id: int, limit: int) -> list[dict[str, object]]:
        assert session_id == 33
        assert user_id == 1
        assert limit == 200
        return [
            {
                "event_type": "breath",
                "numeric_value": 6,
                "occurred_at": datetime(2025, 1, 3, tzinfo=timezone.utc),
            }
        ]

    monkeypatch.setattr(mindful_routes, "list_mindfulness_session_events", _fake_list_events)

    response = client.get("/mindful/sessions/33/events", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["event_type"] == "breath"


def test_add_mindfulness_session_event(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: int, user_id: int) -> dict[str, object] | None:
        return _sample_session_in_progress()

    async def _fake_append_event(
        session_id: int,
        user_id: int,
        event_type: str,
        **kwargs: object,
    ) -> dict[str, object]:
        assert session_id == 202
        assert user_id == 1
        assert event_type == "bpm"
        return {
            "id": 1,
            "session_id": session_id,
            "event_type": event_type,
            "numeric_value": kwargs.get("numeric_value"),
        }

    monkeypatch.setattr(mindful_routes, "get_mindfulness_session", _fake_get_session)
    monkeypatch.setattr(mindful_routes, "append_mindfulness_session_event", _fake_append_event)

    response = client.post(
        "/mindful/sessions/202/events",
        headers=AUTH_HEADERS,
        json={"event_type": "bpm", "numeric_value": 62.5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["event_type"] == "bpm"
    assert payload["numeric_value"] == 62.5


def test_get_mindfulness_stats_overview(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_overview(user_id: int, range: str | None) -> dict[str, object]:
        assert user_id == 1
        assert range == "30d"
        return {"minutes": 120, "sessions": 9}

    monkeypatch.setattr(mindful_routes, "get_mindful_stats_overview", _fake_get_overview)

    response = client.get("/mindful/stats/overview", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["minutes"] == 120


def test_get_mindfulness_stats_daily(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_daily(user_id: int, days: int, exercise_type: str | None) -> list[dict[str, object]]:
        assert user_id == 1
        assert days == 30
        assert exercise_type is None
        return [{"date": "2025-01-01", "minutes": 15}]

    monkeypatch.setattr(mindful_routes, "get_mindful_daily_minutes", _fake_get_daily)

    response = client.get("/mindful/stats/daily", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["minutes"] == 15


def test_get_active_mindfulness_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_active_session(user_id: int) -> dict[str, object] | None:
        assert user_id == 1
        return _sample_session_in_progress()

    monkeypatch.setattr(mindful_routes, "get_active_mindfulness_session", _fake_get_active_session)

    response = client.get("/mindful/sessions/active", headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["status"] == "in_progress"
