"""Script to load mock data for a specific user into the database."""

import asyncio
import json
from pathlib import Path

from auth import DuplicateUserError, create_user
from db import db_session, init_db


async def _get_existing_user(user_email: str) -> dict[str, object] | None:
    async with db_session() as conn:
        record = await conn.fetchrow(
            """
            SELECT id, email, is_guest, created_at
            FROM auth_users
            WHERE email = $1
            """,
            user_email,
        )
    return dict(record) if record else None


async def load_mock_data(user_email: str, password: str) -> None:
    """Load mock data for the given user."""

    await init_db()

    try:
        user = await create_user(user_email, password)
    except DuplicateUserError:
        user = await _get_existing_user(user_email)
        if not user:
            raise

    user_id = user["id"]

    mock_file = Path(__file__).parent / "mock_data.json"
    with mock_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    mindfulness_sessions = data.get("mindfulness_sessions", [])
    mindfulness_events = data.get("mindfulness_session_events", [])
    sleep_sessions = data.get("sleep_sessions", [])
    sleep_stages = data.get("sleep_stages", [])

    async with db_session() as conn:
        async with conn.transaction():
            # Clear existing mock data for this user to keep idempotent runs
            await conn.execute("DELETE FROM mindfulness_session_events WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM mindfulness_sessions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM sleep_stages WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM sleep_events WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM sleep_sessions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM mood_entries WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM stress_assessments WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM behavioral_events WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM conversation_behavior WHERE user_id = $1", user_id)

            mindfulness_session_ids: list[int] = []
            for session in mindfulness_sessions:
                row = await conn.fetchrow(
                    """
                    INSERT INTO mindfulness_sessions (
                        user_id, exercise_type, goal_code, planned_duration_seconds,
                        actual_duration_seconds, start_at, end_at, score_restful, score_focus,
                        tags, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                    """,
                    user_id,
                    session["exercise_type"],
                    session.get("goal_code"),
                    session["planned_duration_seconds"],
                    session.get("actual_duration_seconds"),
                    session["start_at"],
                    session.get("end_at"),
                    session.get("score_restful"),
                    session.get("score_focus"),
                    session.get("tags"),
                    session.get("metadata"),
                )
                mindfulness_session_ids.append(row["id"])

            for event in mindfulness_events:
                idx = event.get("session_index")
                if idx is None or idx < 0 or idx >= len(mindfulness_session_ids):
                    continue
                session_id = mindfulness_session_ids[idx]
                await conn.execute(
                    """
                    INSERT INTO mindfulness_session_events (
                        session_id, user_id, event_type, numeric_value, text_value, occurred_at
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    session_id,
                    user_id,
                    event["event_type"],
                    event.get("numeric_value"),
                    event.get("text_value"),
                    event["occurred_at"],
                )

            sleep_session_ids: list[int] = []
            for sleep in sleep_sessions:
                row = await conn.fetchrow(
                    """
                    INSERT INTO sleep_sessions (
                        user_id, start_at, end_at, in_bed_start_at, in_bed_end_at,
                        total_duration_minutes, time_in_bed_minutes, sleep_efficiency,
                        latency_minutes, awakenings_count, rem_minutes, deep_minutes,
                        light_minutes, awake_minutes, heart_rate_avg, score_overall,
                        quality_label, device_source, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                    RETURNING id
                    """,
                    user_id,
                    sleep["start_at"],
                    sleep.get("end_at"),
                    sleep.get("in_bed_start_at"),
                    sleep.get("in_bed_end_at"),
                    sleep.get("total_duration_minutes"),
                    sleep.get("time_in_bed_minutes"),
                    sleep.get("sleep_efficiency"),
                    sleep.get("latency_minutes"),
                    sleep.get("awakenings_count"),
                    sleep.get("rem_minutes"),
                    sleep.get("deep_minutes"),
                    sleep.get("light_minutes"),
                    sleep.get("awake_minutes"),
                    sleep.get("heart_rate_avg"),
                    sleep.get("score_overall"),
                    sleep.get("quality_label"),
                    sleep.get("device_source"),
                    sleep.get("metadata"),
                )
                sleep_session_ids.append(row["id"])

            for stage in sleep_stages:
                idx = stage.get("session_index")
                if idx is None or idx < 0 or idx >= len(sleep_session_ids):
                    continue
                session_id = sleep_session_ids[idx]
                await conn.execute(
                    """
                    INSERT INTO sleep_stages (
                        session_id, user_id, stage, start_at, end_at, duration_seconds, movement_index
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    session_id,
                    user_id,
                    stage["stage"],
                    stage["start_at"],
                    stage["end_at"],
                    stage["duration_seconds"],
                    stage.get("movement_index"),
                )

            for mood in data.get("mood_entries", []):
                await conn.execute(
                    """
                    INSERT INTO mood_entries (
                        user_id, mood_value, mood_label, note, improvement_flag, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    user_id,
                    mood["mood_value"],
                    mood["mood_label"],
                    mood.get("note"),
                    mood.get("improvement_flag"),
                    mood["created_at"],
                )

            for stress in data.get("stress_assessments", []):
                await conn.execute(
                    """
                    INSERT INTO stress_assessments (
                        user_id, score, qualitative_label, context_note, created_at
                    ) VALUES ($1, $2, $3, $4, $5)
                    """,
                    user_id,
                    stress["score"],
                    stress["qualitative_label"],
                    stress.get("context_note"),
                    stress["created_at"],
                )

            for event in data.get("behavioral_events", []):
                await conn.execute(
                    """
                    INSERT INTO behavioral_events (
                        user_id, event_type, numeric_value, occurred_at
                    ) VALUES ($1, $2, $3, $4)
                    """,
                    user_id,
                    event["event_type"],
                    event.get("numeric_value"),
                    event["occurred_at"],
                )

            for conv in data.get("conversation_behavior", []):
                await conn.execute(
                    """
                    INSERT INTO conversation_behavior (
                        user_id, role, content, intent, sentiment, occurred_at
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    user_id,
                    conv["role"],
                    conv.get("content"),
                    conv.get("intent"),
                    conv.get("sentiment"),
                    conv["occurred_at"],
                )

    print(f"Mock data loaded for user {user_email}")


if __name__ == "__main__":
    asyncio.run(load_mock_data("hello098@gmail.com", "hello123"))