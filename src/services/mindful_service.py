"""Service helpers for mindfulness catalogue, sessions, and analytics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from db import db_session


MINDFULNESS_MIN_DURATION_SECONDS = 60


def _clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, float(value)))


def _range_to_interval(range_key: str | None) -> str | None:
    if not range_key:
        return None
    key = range_key.lower().strip()
    mapping = {
        "7d": "7 days",
        "30d": "30 days",
        "90d": "90 days",
        "180d": "180 days",
        "365d": "365 days",
        "1y": "1 year",
    }
    if key in mapping:
        return mapping[key]
    if key.endswith("d") and key[:-1].isdigit():
        return f"{int(key[:-1])} days"
    if key.endswith("w") and key[:-1].isdigit():
        weeks = int(key[:-1])
        return f"{weeks * 7} days"
    return None


async def list_mindfulness_goals(exercise_type: str | None = None) -> list[dict[str, Any]]:
    query = (
        "SELECT code, title, short_tagline, description, default_exercise_type, "
        "recommended_durations, recommended_soundscape_slugs, metadata, created_at "
        "FROM mindfulness_goals"
    )
    params: list[Any] = []
    if exercise_type:
        params.append(exercise_type)
        query += " WHERE default_exercise_type = $1"
    query += " ORDER BY title"
    async with db_session() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


async def list_mindfulness_soundscapes(active: bool | None = True) -> list[dict[str, Any]]:
    base_query = (
        "SELECT id, slug, name, description, audio_url, loop_seconds, is_active, created_at "
        "FROM mindfulness_soundscapes"
    )
    params: list[Any] = []
    if active is None:
        query = base_query + " ORDER BY name"
        async with db_session() as conn:
            rows = await conn.fetch(query)
    else:
        params.append(active)
        query = base_query + " WHERE is_active = $1 ORDER BY name"
        async with db_session() as conn:
            rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


async def create_mindfulness_session(
    user_id: int,
    *,
    exercise_type: str,
    planned_duration_minutes: int,
    goal_code: str | None = None,
    soundscape_id: int | None = None,
    metadata: dict | None = None,
    tags: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    planned_seconds = max(int(planned_duration_minutes) * 60, 1)
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mindfulness_sessions (
                user_id, exercise_type, goal_code, soundscape_id, planned_duration_seconds, tags, metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
            """,
            user_id,
            exercise_type,
            goal_code,
            soundscape_id,
            planned_seconds,
            list(tags) if tags else None,
            metadata,
        )
    return dict(row) if row else None


async def get_mindfulness_session(session_id: int, user_id: int) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mindfulness_sessions WHERE id = $1 AND user_id = $2",
            session_id,
            user_id,
        )
    return dict(row) if row else None


async def query_mindfulness_sessions(
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
    exercise_type: str | None = None,
    goal_code: str | None = None,
    date_range: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    conditions = ["user_id = $1"]
    params: list[Any] = [user_id]

    if exercise_type:
        params.append(exercise_type)
        conditions.append(f"exercise_type = ${len(params)}")
    if goal_code:
        params.append(goal_code)
        conditions.append(f"goal_code = ${len(params)}")
    interval = _range_to_interval(date_range)
    if interval:
        params.append(interval)
        conditions.append(f"start_at >= now() - ${len(params)}::interval")

    where_clause = " AND ".join(conditions)
    params.append(limit)
    limit_index = len(params)
    params.append(offset)
    offset_index = len(params)

    query = (
        f"SELECT * FROM mindfulness_sessions WHERE {where_clause} "
        f"ORDER BY start_at DESC LIMIT ${limit_index} OFFSET ${offset_index}"
    )

    async with db_session() as conn:
        rows = await conn.fetch(query, *params)

    next_offset = offset + len(rows) if len(rows) == limit else None
    return [dict(row) for row in rows], next_offset


async def update_mindfulness_session_progress(
    session_id: int,
    user_id: int,
    *,
    cycles_completed: int | None = None,
    elapsed_seconds: int | None = None,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = [session_id, user_id]

    if cycles_completed is not None:
        params.append(cycles_completed)
        sets.append(f"cycles_completed = ${len(params)}")
    if elapsed_seconds is not None:
        params.append(max(int(elapsed_seconds), 0))
        sets.append(f"actual_duration_seconds = ${len(params)}")
    if metadata is not None:
        params.append(metadata)
        sets.append(f"metadata = COALESCE(metadata, '{{}}'::jsonb) || ${len(params)}::jsonb")

    if not sets:
        return await get_mindfulness_session(session_id, user_id)

    query = (
        "UPDATE mindfulness_sessions "
        f"SET {', '.join(sets)} "
        "WHERE id = $1 AND user_id = $2 AND end_at IS NULL RETURNING *"
    )

    async with db_session() as conn:
        row = await conn.fetchrow(query, *params)

    if row is None:
        return await get_mindfulness_session(session_id, user_id)
    return dict(row)


def _compute_restful_score(ratings: Mapping[str, Any]) -> float | None:
    rating_relaxation = ratings.get("rating_relaxation")
    stress_before = ratings.get("rating_stress_before")
    stress_after = ratings.get("rating_stress_after")
    if rating_relaxation is None and stress_before is None and stress_after is None:
        return None
    delta_stress = 0
    if stress_before is not None and stress_after is not None:
        delta_stress = stress_before - stress_after
    base = 50 + (delta_stress * 5)
    if rating_relaxation is not None:
        base += rating_relaxation * 3
    return _clamp_score(base)


def _compute_focus_score(
    goal_code: str | None,
    ratings: Mapping[str, Any],
    actual_seconds: int,
    planned_seconds: int,
) -> float | None:
    if not goal_code or not goal_code.startswith("focus"):
        return None
    ratio = 0.0
    if planned_seconds > 0:
        ratio = min(actual_seconds / planned_seconds, 2.0)
    mood_before = ratings.get("rating_mood_before")
    mood_after = ratings.get("rating_mood_after")
    mood_delta = 0
    if mood_before is not None and mood_after is not None:
        mood_delta = mood_after - mood_before
    base = 40 + (ratio * 30) + (mood_delta * 5)
    return _clamp_score(base)


async def complete_mindfulness_session(
    session_id: int,
    user_id: int,
    *,
    cycles_completed: int | None = None,
    rating_relaxation: int | None = None,
    rating_stress_before: int | None = None,
    rating_stress_after: int | None = None,
    rating_mood_before: int | None = None,
    rating_mood_after: int | None = None,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    async with db_session() as conn:
        current_row = await conn.fetchrow(
            "SELECT * FROM mindfulness_sessions WHERE id = $1 AND user_id = $2",
            session_id,
            user_id,
        )

        if current_row is None:
            return None

        current = dict(current_row)

        start_at: datetime = current_row["start_at"]
        existing_end: datetime | None = current_row["end_at"]
        effective_end = existing_end or datetime.now(timezone.utc)
        actual_seconds = max(int((effective_end - start_at).total_seconds()), 0)
        if actual_seconds == 0:
            actual_seconds = current.get("planned_duration_seconds") or 0

        ratings: dict[str, Any] = {
            "rating_relaxation": rating_relaxation if rating_relaxation is not None else current.get("rating_relaxation"),
            "rating_stress_before": rating_stress_before if rating_stress_before is not None else current.get("rating_stress_before"),
            "rating_stress_after": rating_stress_after if rating_stress_after is not None else current.get("rating_stress_after"),
            "rating_mood_before": rating_mood_before if rating_mood_before is not None else current.get("rating_mood_before"),
            "rating_mood_after": rating_mood_after if rating_mood_after is not None else current.get("rating_mood_after"),
        }

        rating_updates_present = any(
            value is not None
            for value in (
                rating_relaxation,
                rating_stress_before,
                rating_stress_after,
                rating_mood_before,
                rating_mood_after,
            )
        )

        should_compute_scores = (
            current.get("score_restful") is None
            or current.get("score_focus") is None
            or rating_updates_present
            or existing_end is None
        )
        restful_score = current.get("score_restful")
        focus_score = current.get("score_focus")

        if should_compute_scores:
            maybe_restful = _compute_restful_score(ratings)
            maybe_focus = _compute_focus_score(
                current.get("goal_code"),
                ratings,
                actual_seconds,
                current.get("planned_duration_seconds") or 0,
            )
            if maybe_restful is not None:
                restful_score = round(maybe_restful, 2)
            if maybe_focus is not None:
                focus_score = round(maybe_focus, 2)
            elif rating_updates_present and (current.get("goal_code") or "").startswith("focus"):
                focus_score = None

        sets: list[str] = []
        params: list[Any] = [session_id, user_id]

        if existing_end is None:
            sets.append("end_at = now()")
        if current.get("actual_duration_seconds") is None or existing_end is None:
            params.append(actual_seconds)
            sets.append(f"actual_duration_seconds = ${len(params)}")
        if cycles_completed is not None:
            params.append(cycles_completed)
            sets.append(f"cycles_completed = ${len(params)}")

        for column, value in (
            ("rating_relaxation", ratings["rating_relaxation"]),
            ("rating_stress_before", ratings["rating_stress_before"]),
            ("rating_stress_after", ratings["rating_stress_after"]),
            ("rating_mood_before", ratings["rating_mood_before"]),
            ("rating_mood_after", ratings["rating_mood_after"]),
        ):
            if value is not None:
                params.append(value)
                sets.append(f"{column} = ${len(params)}")

        if should_compute_scores:
            if restful_score is not None:
                params.append(restful_score)
                sets.append(f"score_restful = ${len(params)}")
            else:
                sets.append("score_restful = NULL")
            if focus_score is not None:
                params.append(focus_score)
                sets.append(f"score_focus = ${len(params)}")
            elif (current.get("goal_code") or "").startswith("focus"):
                sets.append("score_focus = NULL")

        if metadata is not None:
            params.append(metadata)
            sets.append(f"metadata = COALESCE(metadata, '{{}}'::jsonb) || ${len(params)}::jsonb")

        if not sets:
            return dict(current)

        query = (
            "UPDATE mindfulness_sessions "
            f"SET {', '.join(sets)} "
            "WHERE id = $1 AND user_id = $2 RETURNING *"
        )

        updated = await conn.fetchrow(query, *params)

    return dict(updated) if updated else dict(current)


async def append_mindfulness_session_event(
    session_id: int,
    user_id: int,
    event_type: str,
    *,
    numeric_value: float | None = None,
    text_value: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mindfulness_session_events (
                session_id, user_id, event_type, numeric_value, text_value, occurred_at, metadata
            ) VALUES ($1,$2,$3,$4,$5, COALESCE($6, now()), $7)
            RETURNING *
            """,
            session_id,
            user_id,
            event_type,
            numeric_value,
            text_value,
            occurred_at,
            metadata,
        )
    return dict(row) if row else None


async def list_mindfulness_session_events(
    session_id: int,
    user_id: int,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    async with db_session() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, numeric_value, text_value, occurred_at, metadata, created_at
            FROM mindfulness_session_events
            WHERE session_id = $1 AND user_id = $2
            ORDER BY occurred_at ASC
            LIMIT $3
            """,
            session_id,
            user_id,
            limit,
        )
    return [dict(row) for row in rows]


async def get_active_mindfulness_session(user_id: int) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM mindfulness_sessions
            WHERE user_id = $1 AND end_at IS NULL
            ORDER BY start_at DESC
            LIMIT 1
            """,
            user_id,
        )
    return dict(row) if row else None


async def get_mindful_stats_overview(user_id: int, range_key: str | None = None) -> dict[str, Any]:
    interval = _range_to_interval(range_key) or "30 days"
    async with db_session() as conn:
        aggregate = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(actual_duration_seconds)::numeric / 60.0, 0)::float AS total_minutes,
                COALESCE(SUM(actual_duration_seconds)::numeric / 3600.0, 0)::float AS total_hours,
                COUNT(*) FILTER (
                    WHERE actual_duration_seconds IS NOT NULL AND actual_duration_seconds >= $2 AND end_at IS NOT NULL
                ) AS sessions_count,
                COALESCE(AVG(actual_duration_seconds)::numeric / 60.0, 0)::float AS avg_session_minutes
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND end_at IS NOT NULL
              AND start_at >= now() - $3::interval
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
            interval,
        )

        by_type_rows = await conn.fetch(
            """
            SELECT exercise_type,
                   COALESCE(SUM(actual_duration_seconds)::numeric / 60.0, 0)::float AS minutes,
                   COUNT(*) AS sessions
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND end_at IS NOT NULL
              AND start_at >= now() - $3::interval
            GROUP BY exercise_type
            ORDER BY minutes DESC
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
            interval,
        )

        last_session = await conn.fetchrow(
            """
            SELECT *
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND end_at IS NOT NULL
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND start_at >= now() - $3::interval
            ORDER BY end_at DESC
            LIMIT 1
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
            interval,
        )

        streak_rows = await conn.fetch(
            """
            SELECT DISTINCT (end_at AT TIME ZONE 'UTC')::date AS session_date
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND end_at IS NOT NULL
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND end_at >= (CURRENT_DATE - INTERVAL '400 days')
            ORDER BY session_date DESC
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
        )

    total_minutes = float(aggregate["total_minutes"]) if aggregate else 0.0
    total_hours = float(aggregate["total_hours"]) if aggregate else 0.0
    sessions_count = int(aggregate["sessions_count"]) if aggregate else 0
    avg_session_minutes = float(aggregate["avg_session_minutes"]) if aggregate else 0.0

    by_exercise_type = [
        {
            "exercise_type": row["exercise_type"],
            "minutes": float(row["minutes"]),
            "sessions": int(row["sessions"]),
        }
        for row in by_type_rows
    ]

    last_session_payload: dict[str, Any] | None = None
    if last_session:
        last_session_dict = dict(last_session)
        actual = last_session_dict.get("actual_duration_seconds") or 0
        last_session_payload = {
            "id": last_session_dict.get("id"),
            "exercise_type": last_session_dict.get("exercise_type"),
            "end_at": last_session_dict.get("end_at"),
            "minutes": round(actual / 60.0, 2) if actual else 0.0,
            "score_restful": float(last_session_dict["score_restful"]) if last_session_dict.get("score_restful") is not None else None,
            "score_focus": float(last_session_dict["score_focus"]) if last_session_dict.get("score_focus") is not None else None,
        }

    streak_dates = {row["session_date"] for row in streak_rows if row["session_date"] is not None}
    today = datetime.now(timezone.utc).date()
    streak = 0
    cursor = today
    while cursor in streak_dates:
        streak += 1
        cursor = cursor - timedelta(days=1)

    return {
        "range": range_key or "30d",
        "total_minutes": round(total_minutes, 2),
        "total_hours": round(total_hours, 2),
        "by_exercise_type": by_exercise_type,
        "streak_days": streak,
        "sessions_count": sessions_count,
        "avg_session_minutes": round(avg_session_minutes, 2) if sessions_count else 0.0,
        "last_session": last_session_payload,
    }


async def get_mindful_daily_minutes(
    user_id: int,
    *,
    days: int = 30,
    exercise_type: str | None = None,
) -> list[dict[str, Any]]:
    interval = f"{max(days, 1)} days"
    async with db_session() as conn:
        try:
            params: list[Any] = [user_id, interval]
            query = (
                "SELECT day::date AS day, exercise_type, minutes "
                "FROM mindful_daily_minutes "
                "WHERE user_id = $1 AND day >= date_trunc('day', now() - $2::interval)"
            )
            if exercise_type:
                params.append(exercise_type)
                query += f" AND exercise_type = ${len(params)}"
            query += " ORDER BY day"
            rows = await conn.fetch(query, *params)
        except Exception:
            params = [user_id, MINDFULNESS_MIN_DURATION_SECONDS, interval]
            query = (
                "SELECT date_trunc('day', COALESCE(end_at, start_at))::date AS day, exercise_type, "
                "COALESCE(SUM(actual_duration_seconds)::numeric / 60.0, 0)::float AS minutes "
                "FROM mindfulness_sessions "
                "WHERE user_id = $1 "
                "AND actual_duration_seconds IS NOT NULL "
                "AND actual_duration_seconds >= $2 "
                "AND COALESCE(end_at, start_at) >= now() - $3::interval"
            )
            if exercise_type:
                params.append(exercise_type)
                query += f" AND exercise_type = ${len(params)}"
            query += " GROUP BY day, exercise_type ORDER BY day"
            rows = await conn.fetch(query, *params)

    items: list[dict[str, Any]] = []
    for row in rows:
        day_value = row["day"]
        if isinstance(day_value, datetime):
            day_iso = day_value.date().isoformat()
        elif isinstance(day_value, date):
            day_iso = day_value.isoformat()
        else:
            day_iso = str(day_value)
        minutes_value = float(row["minutes"]) if row["minutes"] is not None else 0.0
        items.append(
            {
                "day": day_iso,
                "minutes": round(minutes_value, 2),
                "exercise_type": row["exercise_type"],
            }
        )
    return items
