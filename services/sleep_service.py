from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from db import db_session


def _serialize_schedule(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    def _t(v):
        return v.strftime("%H:%M:%S") if v is not None else None
    return {
        "id": record["id"],
        "bedtime_local": _t(record.get("bedtime_local")),
        "wake_time_local": _t(record.get("wake_time_local")),
        "timezone": record.get("timezone"),
        "active_days": list(record.get("active_days") or []),
        "target_duration_minutes": record.get("target_duration_minutes"),
        "auto_set_alarm": record.get("auto_set_alarm"),
        "show_stats_auto": record.get("show_stats_auto"),
        "is_active": record.get("is_active"),
        "metadata": record.get("metadata"),
        "created_at": record.get("created_at").isoformat() if record.get("created_at") else None,
        "updated_at": record.get("updated_at").isoformat() if record.get("updated_at") else None,
    }


async def get_active_schedule(user_id: int) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, bedtime_local, wake_time_local, timezone, active_days, target_duration_minutes,
                   auto_set_alarm, show_stats_auto, is_active, metadata, created_at, updated_at
            FROM sleep_schedule
            WHERE user_id = $1 AND is_active = TRUE
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            user_id,
        )
    return _serialize_schedule(row)


async def create_schedule(user_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    async with db_session() as conn:
        await conn.execute("UPDATE sleep_schedule SET is_active = FALSE WHERE user_id = $1", user_id)
        row = await conn.fetchrow(
            """
            INSERT INTO sleep_schedule (
                user_id, bedtime_local, wake_time_local, timezone, active_days,
                target_duration_minutes, auto_set_alarm, show_stats_auto, is_active, metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,TRUE,$9)
            RETURNING id, bedtime_local, wake_time_local, timezone, active_days,
                      target_duration_minutes, auto_set_alarm, show_stats_auto, is_active,
                      metadata, created_at, updated_at
            """,
            user_id,
            payload["bedtime_local"],
            payload["wake_time_local"],
            payload["timezone"],
            payload["active_days"],
            payload.get("target_duration_minutes"),
            payload.get("auto_set_alarm", False),
            payload.get("show_stats_auto", True),
            payload.get("metadata"),
        )
    return _serialize_schedule(row)  # type: ignore[arg-type]


async def update_schedule(user_id: int, schedule_id: int, updates: Mapping[str, Any]) -> dict[str, Any] | None:
    async with db_session() as conn:
        assignments: list[str] = []
        params: list[Any] = []
        for column in (
            "bedtime_local",
            "wake_time_local",
            "timezone",
            "active_days",
            "target_duration_minutes",
            "auto_set_alarm",
            "show_stats_auto",
            "is_active",
            "metadata",
        ):
            if column in updates:
                assignments.append(f"{column} = ${len(params) + 1}")
                params.append(updates[column])

        assignments.append("updated_at = now()")
        params.extend([user_id, schedule_id])

        row = await conn.fetchrow(
            f"""
            UPDATE sleep_schedule
            SET {', '.join(assignments)}
            WHERE user_id = ${len(params) - 1} AND id = ${len(params)}
            RETURNING id, bedtime_local, wake_time_local, timezone, active_days,
                      target_duration_minutes, auto_set_alarm, show_stats_auto, is_active,
                      metadata, created_at, updated_at
            """,
            *params,
        )

        if row and updates.get("is_active"):
            await conn.execute(
                "UPDATE sleep_schedule SET is_active = FALSE WHERE user_id = $1 AND id <> $2",
                user_id,
                schedule_id,
            )

    return _serialize_schedule(row) if row else None


# --- Sessions ---

async def start_session(user_id: int, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    async with db_session() as conn:
        active = await conn.fetchrow(
            "SELECT id FROM sleep_sessions WHERE user_id=$1 AND end_at IS NULL ORDER BY start_at DESC LIMIT 1",
            user_id,
        )
        if active:
            # Return existing active session to be idempotent
            return {"id": active["id"], "status": "in_progress", "already_active": True}

        row = await conn.fetchrow(
            """
            INSERT INTO sleep_sessions (user_id, schedule_id, start_at, in_bed_start_at, device_source, is_auto, metadata)
            VALUES ($1, $2, now(), $3, $4, FALSE, $5)
            RETURNING id, start_at, schedule_id
            """,
            user_id,
            payload.get("schedule_id"),
            payload.get("in_bed_start_at"),
            payload.get("device_source"),
            payload.get("metadata"),
        )
    return {"id": row["id"], "start_at": row["start_at"].isoformat(), "schedule_id": row["schedule_id"], "status": "in_progress"}


async def append_stage(user_id: int, session_id: int, payload: Mapping[str, Any]) -> None:
    async with db_session() as conn:
        # Ensure session belongs to user
        s = await conn.fetchrow("SELECT id FROM sleep_sessions WHERE id=$1 AND user_id=$2", session_id, user_id)
        if not s:
            raise ValueError("not_found")
        await conn.execute(
            """
            INSERT INTO sleep_stages (session_id, user_id, stage, start_at, end_at, duration_seconds, movement_index, heart_rate_avg, metadata)
            VALUES ($1,$2,$3,$4,$5, EXTRACT(EPOCH FROM ($5 - $4))::int, $6, $7, NULL)
            """,
            session_id,
            user_id,
            payload["stage"],
            payload["start_at"],
            payload["end_at"],
            payload.get("movement_index"),
            payload.get("heart_rate_avg"),
        )


async def complete_session(user_id: int, session_id: int, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    end_at = payload.get("end_at")
    awake_minutes = payload.get("awake_minutes")
    async with db_session() as conn:
        session = await conn.fetchrow(
            """
            SELECT id, start_at, end_at, in_bed_start_at, in_bed_end_at,
                   total_duration_minutes, time_in_bed_minutes,
                   rem_minutes, deep_minutes, light_minutes, awake_minutes,
                   latency_minutes, awakenings_count, sleep_efficiency,
                   score_overall, quality_label
            FROM sleep_sessions WHERE id=$1 AND user_id=$2
            """,
            session_id,
            user_id,
        )
        if not session:
            raise ValueError("not_found")

        if session["end_at"] is None:
            # compute aggregates from stages
            stages = await conn.fetch(
                "SELECT stage, SUM(duration_seconds) AS dur FROM sleep_stages WHERE session_id=$1 GROUP BY stage",
                session_id,
            )
            totals = {r["stage"]: float(r["dur"]) / 60.0 for r in stages}
            rem = totals.get("rem", 0.0)
            deep = totals.get("deep", 0.0)
            light = totals.get("light", 0.0)
            awake = awake_minutes if awake_minutes is not None else totals.get("awake", 0.0)

            # duration
            start_at = session["start_at"]
            ea = end_at or datetime.utcnow()
            total_minutes = (ea - start_at).total_seconds() / 60.0
            time_in_bed = total_minutes  # simple initial approximation
            latency = 0.0
            if session["in_bed_start_at"]:
                latency = max((start_at - session["in_bed_start_at"]).total_seconds() / 60.0, 0)

            efficiency = (total_minutes / time_in_bed * 100.0) if time_in_bed > 0 else None
            awakenings = 0

            # naive score
            target = 480.0
            duration_score = min((total_minutes / target) * 100.0, 100.0)
            efficiency_score = min(efficiency or 0.0, 100.0)
            rem_ratio = (rem / total_minutes) if total_minutes > 0 else 0
            deep_ratio = (deep / total_minutes) if total_minutes > 0 else 0
            rem_score = min((rem_ratio / 0.22) * 100.0, 100.0)
            deep_score = min((deep_ratio / 0.18) * 100.0, 100.0)
            raw = 0.3 * duration_score + 0.2 * efficiency_score + 0.15 * rem_score + 0.15 * deep_score + 0.2 * 80
            score = max(0.0, min(raw, 100.0))
            quality = "poor" if score < 50 else ("fair" if score < 65 else ("good" if score <= 80 else "excellent"))

            row = await conn.fetchrow(
                """
                UPDATE sleep_sessions
                SET end_at = COALESCE($3, now()),
                    total_duration_minutes = $4,
                    time_in_bed_minutes = $5,
                    sleep_efficiency = $6,
                    latency_minutes = $7,
                    awakenings_count = $8,
                    rem_minutes = $9,
                    deep_minutes = $10,
                    light_minutes = $11,
                    awake_minutes = $12,
                    score_overall = $13,
                    quality_label = $14,
                    updated_at = now()
                WHERE id=$1 AND user_id=$2
                RETURNING id, start_at, end_at, total_duration_minutes, rem_minutes, deep_minutes, light_minutes,
                          awake_minutes, sleep_efficiency, latency_minutes, awakenings_count, score_overall, quality_label
                """,
                session_id,
                user_id,
                end_at,
                total_minutes,
                time_in_bed,
                efficiency,
                latency,
                awakenings,
                rem,
                deep,
                light,
                awake,
                score,
                quality,
            )
        else:
            row = session

    return {
        "id": row["id"],
        "start_at": row["start_at"].isoformat() if row.get("start_at") else None,
        "end_at": row["end_at"].isoformat() if row.get("end_at") else None,
        "total_duration_minutes": row.get("total_duration_minutes"),
        "rem_minutes": row.get("rem_minutes"),
        "deep_minutes": row.get("deep_minutes"),
        "light_minutes": row.get("light_minutes"),
        "awake_minutes": row.get("awake_minutes"),
        "sleep_efficiency": row.get("sleep_efficiency"),
        "latency_minutes": row.get("latency_minutes"),
        "awakenings_count": row.get("awakenings_count"),
        "score_overall": row.get("score_overall"),
        "quality_label": row.get("quality_label"),
    }


async def get_session_detail(user_id: int, session_id: int, include_stages: bool = True) -> Mapping[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, start_at, end_at, total_duration_minutes, rem_minutes, deep_minutes, light_minutes,
                   awake_minutes, sleep_efficiency, latency_minutes, awakenings_count, score_overall, quality_label
            FROM sleep_sessions WHERE id=$1 AND user_id=$2
            """,
            session_id,
            user_id,
        )
        if not row:
            return None
        result: dict[str, Any] = {
            "id": row["id"],
            "start_at": row["start_at"].isoformat() if row.get("start_at") else None,
            "end_at": row["end_at"].isoformat() if row.get("end_at") else None,
            "total_duration_minutes": row.get("total_duration_minutes"),
            "rem_minutes": row.get("rem_minutes"),
            "deep_minutes": row.get("deep_minutes"),
            "light_minutes": row.get("light_minutes"),
            "awake_minutes": row.get("awake_minutes"),
            "sleep_efficiency": row.get("sleep_efficiency"),
            "latency_minutes": row.get("latency_minutes"),
            "awakenings_count": row.get("awakenings_count"),
            "score_overall": row.get("score_overall"),
            "quality_label": row.get("quality_label"),
        }
        if include_stages:
            stages = await conn.fetch(
                "SELECT stage, start_at, end_at, duration_seconds, movement_index, heart_rate_avg FROM sleep_stages WHERE session_id=$1 ORDER BY start_at",
                session_id,
            )
            result["stages"] = [
                {
                    "stage": r["stage"],
                    "start_at": r["start_at"].isoformat() if r.get("start_at") else None,
                    "end_at": r["end_at"].isoformat() if r.get("end_at") else None,
                    "duration_seconds": r.get("duration_seconds"),
                    "movement_index": r.get("movement_index"),
                    "heart_rate_avg": r.get("heart_rate_avg"),
                }
                for r in stages
            ]
        return result


async def list_sessions(user_id: int, *, limit: int = 20, offset: int = 0, filters: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    filters = filters or {}
    clauses = ["user_id = $1"]
    params: list[Any] = [user_id]
    if filters.get("from"):
        clauses.append(f"start_at >= ${len(params)+1}")
        params.append(filters["from"])
    if filters.get("to"):
        clauses.append(f"start_at <= ${len(params)+1}")
        params.append(filters["to"])
    if filters.get("min_duration"):
        clauses.append(f"total_duration_minutes >= ${len(params)+1}")
        params.append(filters["min_duration"])
    where = " AND ".join(clauses)

    async with db_session() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, start_at, end_at, total_duration_minutes, score_overall
            FROM sleep_sessions
            WHERE {where}
            ORDER BY start_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params,
            limit,
            offset,
        )
    items = [
        {
            "id": r["id"],
            "start_at": r["start_at"].isoformat() if r.get("start_at") else None,
            "end_at": r["end_at"].isoformat() if r.get("end_at") else None,
            "total_duration_minutes": r.get("total_duration_minutes"),
            "score_overall": r.get("score_overall"),
        }
        for r in rows
    ]
    next_offset = offset + len(items) if len(items) == limit else None
    return {"items": items, "next_offset": next_offset}


async def get_active_session(user_id: int) -> Mapping[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            "SELECT id, start_at, schedule_id FROM sleep_sessions WHERE user_id=$1 AND end_at IS NULL ORDER BY start_at DESC LIMIT 1",
            user_id,
        )
    if not row:
        return None
    return {"id": row["id"], "start_at": row["start_at"].isoformat(), "schedule_id": row["schedule_id"], "status": "in_progress"}


async def get_calendar(user_id: int, month: str | None) -> Mapping[str, Any]:
    # Expect month format YYYY-MM
    async with db_session() as conn:
        if month:
            row = await conn.fetch(
                """
                SELECT to_char(date_trunc('day', start_at), 'YYYY-MM-DD') AS date,
                       SUM(total_duration_minutes) AS duration_minutes,
                       AVG(score_overall) AS score
                FROM sleep_sessions
                WHERE user_id=$1
                  AND to_char(start_at, 'YYYY-MM') = $2
                  AND end_at IS NOT NULL
                GROUP BY 1 ORDER BY 1
                """,
                user_id,
                month,
            )
        else:
            row = await conn.fetch(
                """
                SELECT to_char(date_trunc('day', start_at), 'YYYY-MM-DD') AS date,
                       SUM(total_duration_minutes) AS duration_minutes,
                       AVG(score_overall) AS score
                FROM sleep_sessions
                WHERE user_id=$1 AND end_at IS NOT NULL
                GROUP BY 1 ORDER BY 1 DESC LIMIT 31
                """,
                user_id,
            )
    days = [
        {"date": r["date"], "duration_minutes": float(r["duration_minutes"]) if r.get("duration_minutes") is not None else None, "score": float(r["score"]) if r.get("score") is not None else None}
        for r in row
    ]
    return {"month": month, "days": days}
