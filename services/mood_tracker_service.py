from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from db import db_session
from schemas.mood_tracker_schema import MOOD_VALUE_LABELS, mood_label_for


def _now() -> datetime:
	"""Return a timezone-aware UTC timestamp (patchable in tests)."""

	return datetime.now(timezone.utc)


def _parse_range_value(range_value: str | None, *, default_days: int = 30) -> tuple[str, int | None]:
	"""Normalize range parameter and return (label, days window).

	If `range_value` is "all" returns ("all", None) meaning no time filter.
	"""

	if not range_value:
		return (f"{default_days}d", default_days)
	value = range_value.strip().lower()
	if value in {"all", "max", "full"}:
		return ("all", None)
	if value.endswith("d") and value[:-1].isdigit():
		days = max(1, min(365, int(value[:-1])))
		return (f"{days}d", days)
	if value.endswith("w") and value[:-1].isdigit():
		days = max(1, min(365, int(value[:-1]) * 7))
		return (f"{days}d", days)
	if value.endswith("m") and value[:-1].isdigit():
		days = max(1, min(365, int(value[:-1]) * 30))
		return (f"{days}d", days)
	if value.isdigit():
		days = max(1, min(365, int(value)))
		return (f"{days}d", days)
	return (value, default_days)


def _normalize_note(note: str | None) -> str | None:
	if note is None:
		return None
	trimmed = note.strip()
	return trimmed or None


def _ensure_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
	if metadata is None:
		return None
	return dict(metadata)


def _serialize_entry(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": row["id"],
		"mood_value": row["mood_value"],
		"mood_label": row.get("mood_label") or mood_label_for(row["mood_value"]),
		"note": row.get("note"),
		"improvement_flag": row.get("improvement_flag"),
		"created_at": row["created_at"],
		"metadata": row.get("metadata"),
	}


def _serialize_suggestion(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": row["id"],
		"suggestion_type": row["suggestion_type"],
		"title": row.get("title"),
		"description": row.get("description"),
		"tags": list(row.get("tags") or []),
		"priority": row.get("priority", 3),
		"status": row.get("status"),
		"resolved_at": row.get("resolved_at"),
		"metadata": row.get("metadata"),
		"created_at": row.get("created_at"),
		"updated_at": row.get("updated_at"),
	}


def _slope(points: Sequence[tuple[float, float]]) -> float:
	if len(points) < 2:
		return 0.0
	x_mean = sum(p[0] for p in points) / len(points)
	y_mean = sum(p[1] for p in points) / len(points)
	numerator = sum((x - x_mean) * (y - y_mean) for x, y in points)
	denominator = sum((x - x_mean) ** 2 for x, _ in points)
	if denominator == 0:
		return 0.0
	return numerator / denominator


@dataclass
class MoodEntryListResult:
	items: list[dict[str, Any]]
	next_offset: int | None


async def create_mood_entry(user_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
	mood_value = int(payload["mood_value"])
	mood_label = mood_label_for(mood_value)
	note = _normalize_note(payload.get("note"))
	improvement_flag = payload.get("improvement_flag")
	if improvement_flag is not None:
		improvement_flag = bool(improvement_flag)
	metadata = _ensure_metadata(payload.get("metadata"))
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			INSERT INTO mood_entries (user_id, mood_value, mood_label, note, improvement_flag, metadata)
			VALUES ($1, $2, $3, $4, $5, $6)
			RETURNING id, mood_value, mood_label, note, improvement_flag, metadata, created_at
			""",
			user_id,
			mood_value,
			mood_label,
			note,
			improvement_flag,
			metadata,
		)
	return _serialize_entry(row)


async def list_mood_entries(
	user_id: int,
	*,
	limit: int = 30,
	offset: int = 0,
	filters: Mapping[str, Any] | None = None,
) -> MoodEntryListResult:
	filters = filters or {}
	clauses = ["user_id = $1"]
	params: list[Any] = [user_id]

	if filters.get("from"):
		clauses.append(f"created_at >= ${len(params)+1}")
		params.append(filters["from"])
	if filters.get("to"):
		clauses.append(f"created_at <= ${len(params)+1}")
		params.append(filters["to"])
	if filters.get("mood_min") is not None:
		clauses.append(f"mood_value >= ${len(params)+1}")
		params.append(filters["mood_min"])
	if filters.get("mood_max") is not None:
		clauses.append(f"mood_value <= ${len(params)+1}")
		params.append(filters["mood_max"])
	if filters.get("improvement") is not None:
		clauses.append(f"COALESCE(improvement_flag, FALSE) = ${len(params)+1}")
		params.append(bool(filters["improvement"]))

	order = filters.get("order", "desc").lower()
	if order not in {"asc", "desc"}:
		order = "desc"
	where_clause = " AND ".join(clauses)

	async with db_session() as conn:
		rows = await conn.fetch(
			f"""
			SELECT id, mood_value, mood_label, note, improvement_flag, metadata, created_at
			FROM mood_entries
			WHERE {where_clause}
			ORDER BY created_at {order.upper()}
			LIMIT ${len(params)+1} OFFSET ${len(params)+2}
			""",
			*params,
			limit,
			offset,
		)

	items = [_serialize_entry(row) for row in rows]
	next_offset = offset + len(items) if len(items) == limit else None
	return MoodEntryListResult(items=items, next_offset=next_offset)


async def list_recent_entries(user_id: int, *, limit: int = 14, order: str = "desc") -> list[dict[str, Any]]:
	result = await list_mood_entries(user_id, limit=limit, offset=0, filters={"order": order})
	return result.items


async def get_mood_entry(user_id: int, entry_id: int) -> dict[str, Any] | None:
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			SELECT id, mood_value, mood_label, note, improvement_flag, metadata, created_at
			FROM mood_entries
			WHERE id = $1 AND user_id = $2
			""",
			entry_id,
			user_id,
		)
	if not row:
		return None
	return _serialize_entry(row)


async def update_mood_entry(user_id: int, entry_id: int, updates: Mapping[str, Any]) -> dict[str, Any] | None:
	assignments: list[str] = []
	params: list[Any] = []
	if "note" in updates:
		note = _normalize_note(updates["note"])
		assignments.append(f"note = ${len(params)+1}")
		params.append(note)
	if "improvement_flag" in updates:
		assignments.append(f"improvement_flag = ${len(params)+1}")
		params.append(None if updates["improvement_flag"] is None else bool(updates["improvement_flag"]))
	if "metadata" in updates:
		assignments.append(f"metadata = ${len(params)+1}")
		params.append(_ensure_metadata(updates["metadata"]))

	if not assignments:
		return await get_mood_entry(user_id, entry_id)

	async with db_session() as conn:
		row = await conn.fetchrow(
			f"""
			UPDATE mood_entries
			SET {', '.join(assignments)}
			WHERE id = ${len(params)+1} AND user_id = ${len(params)+2}
			RETURNING id, mood_value, mood_label, note, improvement_flag, metadata, created_at
			""",
			*params,
			entry_id,
			user_id,
		)
	if not row:
		return None
	return _serialize_entry(row)


async def delete_mood_entry(user_id: int, entry_id: int) -> bool:
	async with db_session() as conn:
		row = await conn.fetchrow(
			"DELETE FROM mood_entries WHERE id = $1 AND user_id = $2 RETURNING id",
			entry_id,
			user_id,
		)
	return bool(row)


async def _fetch_daily_stats(
	conn,
	user_id: int,
	*,
	start: datetime | None,
	end: datetime | None,
) -> list[dict[str, Any]]:
	params: list[Any] = [user_id]
	conditions = ["user_id = $1"]
	if start is not None:
		conditions.append(f"day >= ${len(params)+1}")
		params.append(start)
	if end is not None:
		conditions.append(f"day < ${len(params)+1}")
		params.append(end)
	query = (
		"SELECT day, avg_mood_value, mood_swing, entries_count FROM mood_daily_stats "
		f"WHERE {' AND '.join(conditions)} ORDER BY day"
	)
	try:
		rows = await conn.fetch(query, *params)
	except Exception:
		# Fallback: compute on the fly from raw entries.
		params = [user_id]
		conditions = ["user_id = $1"]
		if start is not None:
			conditions.append(f"created_at >= ${len(params)+1}")
			params.append(start)
		if end is not None:
			conditions.append(f"created_at < ${len(params)+1}")
			params.append(end)
		rows = await conn.fetch(
			"""
			SELECT date_trunc('day', created_at) AS day,
			       AVG(mood_value)::float AS avg_mood_value,
			       (MAX(mood_value) - MIN(mood_value))::float AS mood_swing,
			       COUNT(*) AS entries_count
			FROM mood_entries
			WHERE {conditions}
			GROUP BY 1
			ORDER BY 1
			""".format(conditions=" AND ".join(conditions)),
			*params,
		)

	stats: list[dict[str, Any]] = []
	for row in rows:
		day_value = row["day"]
		if isinstance(day_value, datetime):
			day = day_value.date()
		else:  # some drivers may behave differently
			day = getattr(day_value, "date", lambda: day_value)()
		stats.append(
			{
				"day": day,
				"avg_mood_value": (float(row["avg_mood_value"]) if row["avg_mood_value"] is not None else None),
				"mood_swing": (float(row["mood_swing"]) if row["mood_swing"] is not None else None),
				"entries": int(row["entries_count"]),
			}
		)
	return stats


async def get_daily_stats(user_id: int, days: int) -> list[dict[str, Any]]:
	now = _now()
	start = now - timedelta(days=days)
	async with db_session() as conn:
		return await _fetch_daily_stats(conn, user_id, start=start, end=None)


async def _aggregate_distribution(
	conn,
	user_id: int,
	*,
	start: datetime | None,
	end: datetime | None,
) -> dict[str, int]:
	params: list[Any] = [user_id]
	conditions = ["user_id = $1"]
	if start is not None:
		conditions.append(f"created_at >= ${len(params)+1}")
		params.append(start)
	if end is not None:
		conditions.append(f"created_at < ${len(params)+1}")
		params.append(end)
	query = (
		"SELECT mood_label, COUNT(*) AS count FROM mood_entries "
		f"WHERE {' AND '.join(conditions)} GROUP BY mood_label"
	)
	rows = await conn.fetch(query, *params)
	distribution = {label: 0 for label in MOOD_VALUE_LABELS.values()}
	for row in rows:
		label = row["mood_label"]
		distribution[label] = int(row["count"])
	return distribution


async def _aggregate_summary_metrics(
	conn,
	user_id: int,
	*,
	start: datetime | None,
	end: datetime | None,
) -> dict[str, Any]:
	params: list[Any] = [user_id]
	conditions = ["user_id = $1"]
	if start is not None:
		conditions.append(f"created_at >= ${len(params)+1}")
		params.append(start)
	if end is not None:
		conditions.append(f"created_at < ${len(params)+1}")
		params.append(end)
	stats_row = await conn.fetchrow(
		"""
		SELECT AVG(mood_value)::float AS avg_mood,
		       MIN(mood_value) AS min_mood,
		       MAX(mood_value) AS max_mood,
		       COUNT(*) FILTER (WHERE improvement_flag IS TRUE) AS improvement_entries
		FROM mood_entries
		WHERE {conditions}
		""".format(conditions=" AND ".join(conditions)),
		*params,
	)
	if not stats_row:
		return {"avg_mood": None, "mood_swing": None, "improvement_entries": 0}
	min_mood = stats_row["min_mood"]
	max_mood = stats_row["max_mood"]
	mood_swing = None
	if min_mood is not None and max_mood is not None:
		mood_swing = float(max_mood - min_mood)
	return {
		"avg_mood": float(stats_row["avg_mood"]) if stats_row["avg_mood"] is not None else None,
		"mood_swing": mood_swing,
		"improvement_entries": int(stats_row["improvement_entries"] or 0),
	}


async def get_summary_overview(user_id: int, range_value: str | None) -> dict[str, Any]:
	normalized_range, days = _parse_range_value(range_value)
	now = _now()
	start = now - timedelta(days=days) if days is not None else None
	async with db_session() as conn:
		current_row = await conn.fetchrow(
			"""
			SELECT id, mood_value, mood_label, note, improvement_flag, metadata, created_at
			FROM mood_entries
			WHERE user_id = $1
			ORDER BY created_at DESC
			LIMIT 1
			""",
			user_id,
		)
		current = _serialize_entry(current_row) if current_row else {
			"mood_value": None,
			"mood_label": None,
			"created_at": None,
		}

		stats = await _fetch_daily_stats(conn, user_id, start=start, end=None)
		distribution = await _aggregate_distribution(conn, user_id, start=start, end=None)
		summary_metrics = await _aggregate_summary_metrics(conn, user_id, start=start, end=None)

		daily_points = [(float(index), row["avg_mood_value"]) for index, row in enumerate(stats) if row["avg_mood_value"] is not None]
		slope = _slope(daily_points)
		direction = "flat"
		if slope > 0.05:
			direction = "up"
		elif slope < -0.05:
			direction = "down"

		delta_vs_prev = None
		if days is not None and days > 0:
			prev_end = start
			prev_start = prev_end - timedelta(days=days) if prev_end is not None else None
			if prev_start is not None and prev_end is not None:
				prev_stats = await _aggregate_summary_metrics(conn, user_id, start=prev_start, end=prev_end)
				if summary_metrics["avg_mood"] is not None and prev_stats["avg_mood"] is not None:
					delta_vs_prev = summary_metrics["avg_mood"] - prev_stats["avg_mood"]

	return {
		"range": normalized_range,
		"current": {
			"mood_value": current.get("mood_value"),
			"mood_label": current.get("mood_label"),
			"created_at": current.get("created_at"),
		},
		"trend": {
			"direction": direction,
			"slope": slope,
			"delta_vs_prev_period": delta_vs_prev,
		},
		"distribution": distribution,
		"avg_mood": summary_metrics["avg_mood"],
		"mood_swing": summary_metrics["mood_swing"],
		"improvement_entries": summary_metrics["improvement_entries"],
	}


async def get_distribution(user_id: int, range_value: str | None) -> dict[str, Any]:
	normalized_range, days = _parse_range_value(range_value)
	now = _now()
	start = now - timedelta(days=days) if days is not None else None
	async with db_session() as conn:
		distribution = await _aggregate_distribution(conn, user_id, start=start, end=None)
	return {
		"range": normalized_range,
		"counts": distribution,
	}


async def filter_entries(
	user_id: int,
	*,
	limit: int = 30,
	offset: int = 0,
	filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	result = await list_mood_entries(user_id, limit=limit, offset=offset, filters=filters)
	return {
		"filters": dict(filters or {}),
		"items": result.items,
		"next_offset": result.next_offset,
	}


async def list_suggestions(
	user_id: int,
	*,
	statuses: Iterable[str] | None = None,
	suggestion_types: Iterable[str] | None = None,
	days: int | None = None,
	limit: int = 20,
	offset: int = 0,
) -> MoodEntryListResult:
	clauses = ["user_id = $1"]
	params: list[Any] = [user_id]
	if statuses:
		statuses_list = [status.strip().lower() for status in statuses if status]
		if statuses_list:
			clauses.append(f"status = ANY(${len(params)+1})")
			params.append(statuses_list)
	if suggestion_types:
		types_list = [s.strip().lower() for s in suggestion_types if s]
		if types_list:
			clauses.append(f"suggestion_type = ANY(${len(params)+1})")
			params.append(types_list)
	if days is not None:
		clauses.append(f"created_at >= ${len(params)+1}")
		params.append(_now() - timedelta(days=days))
	query = (
		"SELECT id, suggestion_type, title, description, tags, priority, status, resolved_at, metadata, created_at, updated_at "
		f"FROM mood_suggestions WHERE {' AND '.join(clauses)} "
		"ORDER BY priority ASC, created_at DESC "
		f"LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
	)
	async with db_session() as conn:
		rows = await conn.fetch(query, *params, limit, offset)
	items = [_serialize_suggestion(row) for row in rows]
	next_offset = offset + len(items) if len(items) == limit else None
	return MoodEntryListResult(items=items, next_offset=next_offset)


async def update_suggestion_status(user_id: int, suggestion_id: int, status: str) -> dict[str, Any] | None:
	status = status.strip().lower()
	resolved = status in {"completed", "dismissed"}
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			UPDATE mood_suggestions
			SET status = $3,
			    resolved_at = CASE WHEN $4 THEN COALESCE(resolved_at, now()) ELSE NULL END,
			    updated_at = now()
			WHERE id = $1 AND user_id = $2
			RETURNING id, suggestion_type, title, description, tags, priority, status, resolved_at, metadata, created_at, updated_at
			""",
			suggestion_id,
			user_id,
			status,
			resolved,
		)
	if not row:
		return None
	return _serialize_suggestion(row)


async def list_active_suggestions(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
	async with db_session() as conn:
		rows = await conn.fetch(
			"""
			SELECT id, suggestion_type, title, description, tags, priority, status, resolved_at, metadata, created_at, updated_at
			FROM mood_suggestions
			WHERE user_id = $1 AND status IN ('new', 'acknowledged')
			ORDER BY priority ASC, created_at ASC
			LIMIT $2
			""",
			user_id,
			limit,
		)
	return [_serialize_suggestion(row) for row in rows]


__all__ = [
	"create_mood_entry",
	"list_mood_entries",
	"list_recent_entries",
	"get_mood_entry",
	"update_mood_entry",
	"delete_mood_entry",
	"get_daily_stats",
	"get_summary_overview",
	"get_distribution",
	"filter_entries",
	"list_suggestions",
	"update_suggestion_status",
	"list_active_suggestions",
]

