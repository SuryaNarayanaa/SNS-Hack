"""Script to load mock data for a specific user into the database."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import db_session, init_db
from auth import create_user


async def load_mock_data(user_email: str, password: str):
    """Load mock data for the given user."""
    # Ensure DB is initialized
    await init_db()

    # Create or get user
    user = await create_user(user_email, password)
    user_id = user["id"]

    # Load mock data
    mock_file = Path(__file__).parent / "mock_data.json"
    with open(mock_file, "r") as f:
        data = json.load(f)

    async with db_session() as conn:
        # Insert mindfulness sessions
        for session in data.get("mindfulness_sessions", []):
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
            session_id = row["id"]

            # Insert events for this session
            for event in data.get("mindfulness_session_events", []):
                if event.get("session_id") == session_id:  # Assuming session_id in JSON is placeholder
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

        # Insert sleep sessions
        for sleep in data.get("sleep_sessions", []):
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
            sleep_session_id = row["id"]

            # Insert sleep stages
            for stage in data.get("sleep_stages", []):
                if stage.get("session_id") == sleep_session_id:
                    await conn.execute(
                        """
                        INSERT INTO sleep_stages (
                            session_id, user_id, stage, start_at, end_at, duration_seconds, movement_index
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        sleep_session_id,
                        user_id,
                        stage["stage"],
                        stage["start_at"],
                        stage["end_at"],
                        stage["duration_seconds"],
                        stage.get("movement_index"),
                    )

        # Insert mood entries
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

        # Insert stress assessments
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

        # Insert behavioral events
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

        # Insert conversation behavior
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