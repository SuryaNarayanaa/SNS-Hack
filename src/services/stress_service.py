from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from asyncpg import Record

from db import db_session


QUALITATIVE_LABELS: dict[int, str] = {
	0: "calm",
	1: "normal",
	2: "elevated",
	3: "elevated",
	4: "high",
	5: "extreme",
}


def _qualitative_label(score: int) -> str:
	if score not in QUALITATIVE_LABELS:
		raise ValueError("score must be between 0 and 5 inclusive")
	return QUALITATIVE_LABELS[score]


def _parse_range_days(range_value: str | None, default_days: int = 30) -> int:
	if not range_value:
		return default_days
	range_value = range_value.strip().lower()
	if range_value.endswith("d") and range_value[:-1].isdigit():
		return max(1, min(180, int(range_value[:-1])))
	if range_value.endswith("w") and range_value[:-1].isdigit():
		return max(1, min(180, int(range_value[:-1]) * 7))
	if range_value.endswith("m") and range_value[:-1].isdigit():
		return max(1, min(365, int(range_value[:-1]) * 30))
	if range_value.isdigit():
		return max(1, min(365, int(range_value)))
	return default_days


def _slope_from_points(points: Sequence[tuple[float, float]]) -> float:
	n = len(points)
	if n < 2:
		return 0.0
	x_vals = [p[0] for p in points]
	y_vals = [p[1] for p in points]
	x_mean = sum(x_vals) / n
	y_mean = sum(y_vals) / n
	numerator = sum((x - x_mean) * (y - y_mean) for x, y in points)
	denominator = sum((x - x_mean) ** 2 for x in x_vals)
	if denominator == 0:
		return 0.0
	return numerator / denominator


def _distribution_to_dict(rows: Sequence[Record]) -> dict[str, int]:
	return {row["qualitative_label"]: row["count"] for row in rows}


def _serialize_assessment(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": row["id"],
		"score": row["score"],
		"qualitative_label": row["qualitative_label"],
		"context_note": row.get("context_note"),
		"created_at": row["created_at"],
	}


def _serialize_assessment_detail(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": row["id"],
		"score": row["score"],
		"qualitative_label": row["qualitative_label"],
		"context_note": row.get("context_note"),
		"expression_session_id": row.get("expression_session_id"),
		"metadata": row.get("metadata"),
		"created_at": row["created_at"],
	}


def _serialize_stressor(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": row["id"],
		"slug": row["slug"],
		"name": row.get("name"),
		"description": row.get("description"),
		"is_active": row.get("is_active", True),
		"metadata": row.get("metadata"),
	}


def _serialize_assessment_stressor(row: Mapping[str, Any]) -> dict[str, Any]:
	return {
		"id": row["stressor_id"],
		"slug": row["slug"],
		"name": row.get("name"),
		"impact_level": row.get("impact_level"),
		"impact_score": float(row["impact_score"]) if row.get("impact_score") is not None else None,
		"metadata": row.get("metadata"),
	}


def _normalize_slugs(slugs: Iterable[str]) -> list[str]:
	unique: list[str] = []
	seen: set[str] = set()
	for slug in slugs:
		slug_norm = slug.strip().lower()
		if slug_norm and slug_norm not in seen:
			unique.append(slug_norm)
			seen.add(slug_norm)
	return unique


async def list_stressors(active: bool | None = True) -> list[dict[str, Any]]:
	query = "SELECT id, slug, name, description, is_active, metadata FROM stress_stressors"
	params: list[Any] = []
	if active is True:
		query += " WHERE is_active = TRUE"
	elif active is False:
		query += " WHERE is_active = FALSE"
	query += " ORDER BY name"
	async with db_session() as conn:
		rows = await conn.fetch(query, *params)
	return [_serialize_stressor(row) for row in rows]


async def create_assessment(
	user_id: int,
	score: int,
	stressor_slugs: Sequence[str],
	*,
	context_note: str | None = None,
	expression_session_id: int | None = None,
	metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	slugs = _normalize_slugs(stressor_slugs)
	async with db_session() as conn:
		async with conn.transaction():
			if expression_session_id is not None:
				session_row = await conn.fetchrow(
					"SELECT id FROM stress_expression_sessions WHERE id = $1 AND user_id = $2",
					expression_session_id,
					user_id,
				)
				if not session_row:
					raise ValueError("expression_session_not_found")

			if slugs:
				rows = await conn.fetch(
					"SELECT id, slug FROM stress_stressors WHERE slug = ANY($1)",
					slugs,
				)
				found_map = {row["slug"]: row["id"] for row in rows}
				missing = [slug for slug in slugs if slug not in found_map]
				if missing:
					raise ValueError(f"unknown_stressors:{','.join(missing)}")
			else:
				found_map = {}

			label = _qualitative_label(score)
			assessment_row = await conn.fetchrow(
				"""
				INSERT INTO stress_assessments (user_id, score, qualitative_label, context_note, expression_session_id, metadata)
				VALUES ($1, $2, $3, $4, $5, $6)
				RETURNING id, score, qualitative_label, context_note, expression_session_id, metadata, created_at
				""",
				user_id,
				score,
				label,
				context_note,
				expression_session_id,
				metadata,
			)

			assessment_id = assessment_row["id"]
			if slugs:
				params = [(assessment_id, found_map[slug]) for slug in slugs]
				await conn.executemany(
					"""
					INSERT INTO stress_assessment_stressors (assessment_id, stressor_id)
					VALUES ($1, $2)
					ON CONFLICT DO NOTHING
					""",
					params,
				)

			if expression_session_id is not None:
				await conn.execute(
					"UPDATE stress_expression_sessions SET metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb WHERE id = $1 AND user_id = $2",
					expression_session_id,
					user_id,
					{"linked_assessment_id": assessment_id},
				)

			stressor_details: list[dict[str, Any]] = []
			if params := await conn.fetch(
				"""
				SELECT sas.stressor_id, ss.slug, ss.name, sas.impact_level, sas.impact_score, sas.metadata
				FROM stress_assessment_stressors sas
				JOIN stress_stressors ss ON ss.id = sas.stressor_id
				WHERE sas.assessment_id = $1
				ORDER BY ss.slug
				""",
				assessment_id,
			):
				stressor_details = [_serialize_assessment_stressor(row) for row in params]

	return _serialize_assessment_detail(assessment_row) | {"stressors": stressor_details}


async def list_assessments(
	user_id: int,
	*,
	limit: int = 30,
	offset: int = 0,
	filters: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
	filters = filters or {}
	clauses = ["user_id = $1"]
	params: list[Any] = [user_id]
	if filters.get("from"):
		clauses.append(f"created_at >= ${len(params)+1}")
		params.append(filters["from"])
	if filters.get("to"):
		clauses.append(f"created_at <= ${len(params)+1}")
		params.append(filters["to"])
	if (min_score := filters.get("min_score")) is not None:
		clauses.append(f"score >= ${len(params)+1}")
		params.append(min_score)
	if (max_score := filters.get("max_score")) is not None:
		clauses.append(f"score <= ${len(params)+1}")
		params.append(max_score)

	base_query = "SELECT id, score, qualitative_label, context_note, created_at FROM stress_assessments"
	where_clause = " AND ".join(clauses)
	query = f"{base_query} WHERE {where_clause} ORDER BY created_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
	params.extend([limit, offset])

	async with db_session() as conn:
		rows = await conn.fetch(query, *params)
		if filters.get("stressor"):
			# filter by stressor slug via join
			slug = filters["stressor"].strip().lower()
			rows = [
				row
				for row in rows
				if await conn.fetchval(
					"SELECT 1 FROM stress_assessment_stressors sas JOIN stress_stressors ss ON ss.id = sas.stressor_id WHERE sas.assessment_id = $1 AND ss.slug = $2",
					row["id"],
					slug,
				)
			]

	items = [_serialize_assessment(row) for row in rows]
	next_offset = offset + len(items) if len(items) == limit else None
	return items, next_offset


async def list_recent_assessments(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
	async with db_session() as conn:
		rows = await conn.fetch(
			"""
			SELECT id, score, qualitative_label, context_note, created_at
			FROM stress_assessments
			WHERE user_id = $1
			ORDER BY created_at DESC
			LIMIT $2
			""",
			user_id,
			limit,
		)
	return [_serialize_assessment(row) for row in rows]


async def get_assessment_detail(user_id: int, assessment_id: int) -> dict[str, Any] | None:
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			SELECT id, score, qualitative_label, context_note, expression_session_id, metadata, created_at
			FROM stress_assessments
			WHERE id = $1 AND user_id = $2
			""",
			assessment_id,
			user_id,
		)
		if not row:
			return None
		stressors = await conn.fetch(
			"""
			SELECT sas.stressor_id, ss.slug, ss.name, sas.impact_level, sas.impact_score, sas.metadata
			FROM stress_assessment_stressors sas
			JOIN stress_stressors ss ON ss.id = sas.stressor_id
			WHERE sas.assessment_id = $1
			ORDER BY ss.slug
			""",
			assessment_id,
		)
		stressor_payload = [_serialize_assessment_stressor(s) for s in stressors]
		if row.get("expression_session_id"):
			session = await conn.fetchrow(
				"""
				SELECT id, user_id, started_at, completed_at, capture_type, status, metadata, device_capabilities
				FROM stress_expression_sessions
				WHERE id = $1 AND user_id = $2
				""",
				row["expression_session_id"],
				user_id,
			)
		else:
			session = None

	return _serialize_assessment_detail(row) | {"stressors": stressor_payload, "expression_session": dict(session) if session else None}


async def get_overview(user_id: int, range_value: str | None) -> dict[str, Any]:
	days = _parse_range_days(range_value)
	interval = f"{days} days"
	async with db_session() as conn:
		current = await conn.fetchrow(
			"""
			SELECT id, score, qualitative_label, created_at
			FROM stress_assessments
			WHERE user_id = $1
			ORDER BY created_at DESC
			LIMIT 1
			""",
			user_id,
		)

		distribution_rows = await conn.fetch(
			"""
			SELECT qualitative_label, COUNT(*) AS count
			FROM stress_assessments
			WHERE user_id = $1 AND created_at >= now() - $2::interval
			GROUP BY qualitative_label
			""",
			user_id,
			interval,
		)

		daily_rows = await conn.fetch(
			"""
			SELECT date(created_at) AS day, AVG(score)::float AS avg_score
			FROM stress_assessments
			WHERE user_id = $1 AND created_at >= now() - $2::interval
			GROUP BY day
			ORDER BY day
			""",
			user_id,
			interval,
		)

		points = [(idx, row["avg_score"]) for idx, row in enumerate(daily_rows)]
		slope = _slope_from_points(points)
		trend_direction: str
		if slope > 0.02:
			trend_direction = "up"
		elif slope < -0.02:
			trend_direction = "down"
		else:
			trend_direction = "flat"

		# Period delta vs previous period
		prev_rows = await conn.fetch(
			"""
			SELECT AVG(score)::float AS avg_score
			FROM stress_assessments
			WHERE user_id = $1
			  AND created_at >= now() - $2::interval * 2
			  AND created_at < now() - $2::interval
			""",
			user_id,
			interval,
		)
		current_avg = mean([row["avg_score"] for row in daily_rows]) if daily_rows else None
		prev_avg = prev_rows[0]["avg_score"] if prev_rows and prev_rows[0]["avg_score"] is not None else None
		delta_vs_prev = (current_avg - prev_avg) if (current_avg is not None and prev_avg is not None) else None

		top_stressors = await conn.fetch(
			"""
			SELECT ss.slug, ss.name, AVG(sa.score)::float AS avg_score, AVG(sas.impact_score)::float AS avg_impact_score,
			       MAX(sas.impact_level) FILTER (WHERE sas.impact_level IS NOT NULL) AS impact_level
			FROM stress_assessments sa
			JOIN stress_assessment_stressors sas ON sas.assessment_id = sa.id
			JOIN stress_stressors ss ON ss.id = sas.stressor_id
			WHERE sa.user_id = $1 AND sa.created_at >= now() - $2::interval
			GROUP BY ss.slug, ss.name
			ORDER BY avg_impact_score DESC NULLS LAST, avg_score DESC
			LIMIT 5
			""",
			user_id,
			interval,
		)

		top_payload = [
			{
				"slug": row["slug"],
				"name": row.get("name"),
				"avg_score": row["avg_score"],
				"avg_impact_score": row["avg_impact_score"],
				"impact_level": row.get("impact_level"),
			}
			for row in top_stressors
		]

	return {
		"current": {
			"score": current["score"],
			"qualitative_label": current["qualitative_label"],
			"created_at": current["created_at"],
		} if current else None,
		"trend": {
			"direction": trend_direction if daily_rows else None,
			"slope": slope if daily_rows else None,
			"delta_vs_prev_period": delta_vs_prev,
		},
		"top_stressors": top_payload,
		"distribution": _distribution_to_dict(distribution_rows),
	}


async def get_daily_stats(user_id: int, days: int) -> list[dict[str, Any]]:
	interval = f"{days} days"
	async with db_session() as conn:
		try:
			rows = await conn.fetch(
				"""
				SELECT day, avg_score, assessments
				FROM stress_daily_stats
				WHERE user_id = $1 AND day >= (now() - $2::interval)
				ORDER BY day
				""",
				user_id,
				interval,
			)
		except Exception:
			rows = await conn.fetch(
				"""
				SELECT date(created_at) AS day,
				       AVG(score)::float AS avg_score,
				       COUNT(*) AS assessments
				FROM stress_assessments
				WHERE user_id = $1 AND created_at >= now() - $2::interval
				GROUP BY day
				ORDER BY day
				""",
				user_id,
				interval,
			)
	return [
		{
			"day": row["day"],
			"avg_score": row["avg_score"],
			"assessments": row["assessments"],
		}
		for row in rows
	]


async def get_stressor_stats(user_id: int, days: int, limit: int = 10) -> list[dict[str, Any]]:
	interval = f"{days} days"
	async with db_session() as conn:
		try:
			rows = await conn.fetch(
				"""
				SELECT ss.slug, ss.name, COUNT(DISTINCT sa.id) AS assessments,
				       AVG(sa.score)::float AS avg_score,
				       AVG(sas.impact_score)::float AS avg_impact_score
				FROM stress_assessments sa
				JOIN stress_assessment_stressors sas ON sas.assessment_id = sa.id
				JOIN stress_stressors ss ON ss.id = sas.stressor_id
				WHERE sa.user_id = $1 AND sa.created_at >= now() - $2::interval
				GROUP BY ss.slug, ss.name
				ORDER BY avg_impact_score DESC NULLS LAST, avg_score DESC
				LIMIT $3
				""",
				user_id,
				interval,
				limit,
			)
		except Exception:
			rows = []
	return [
		{
			"slug": row["slug"],
			"name": row.get("name"),
			"assessments": row["assessments"],
			"avg_score": row["avg_score"],
			"avg_impact_score": row["avg_impact_score"],
		}
		for row in rows
	]


async def start_expression_session(
	user_id: int,
	*,
	capture_type: str | None = None,
	metadata: Mapping[str, Any] | None = None,
	device_capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			INSERT INTO stress_expression_sessions (user_id, capture_type, metadata, device_capabilities)
			VALUES ($1, $2, $3, $4)
			RETURNING id, user_id, started_at, completed_at, capture_type, status, metadata, device_capabilities
			""",
			user_id,
			capture_type,
			metadata,
			device_capabilities,
		)
	return dict(row)


async def append_expression_metrics(
	user_id: int,
	session_id: int,
	items: Sequence[Mapping[str, Any]],
) -> int:
	if not items:
		return 0
	payload = []
	for item in items:
		captured_at = item.get("captured_at") or datetime.utcnow()
		payload.append(
			(
				session_id,
				user_id,
				captured_at,
				item.get("heart_rate_bpm"),
				item.get("systolic_bp"),
				item.get("diastolic_bp"),
				item.get("breathing_rate"),
				item.get("expression_primary"),
				item.get("expression_confidence"),
				item.get("stress_inference"),
				item.get("metadata"),
			)
		)
	async with db_session() as conn:
		session = await conn.fetchrow(
			"SELECT id FROM stress_expression_sessions WHERE id = $1 AND user_id = $2",
			session_id,
			user_id,
		)
		if not session:
			raise ValueError("session_not_found")
		await conn.executemany(
			"""
			INSERT INTO stress_expression_metrics (session_id, user_id, captured_at, heart_rate_bpm, systolic_bp, diastolic_bp,
			                                     breathing_rate, expression_primary, expression_confidence, stress_inference, metadata)
			VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
			""",
			payload,
		)
	return len(payload)


async def complete_expression_session(
	user_id: int,
	session_id: int,
	*,
	metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
	async with db_session() as conn:
		async with conn.transaction():
			session = await conn.fetchrow(
				"""
				SELECT id, user_id, started_at, completed_at, capture_type, status, metadata
				FROM stress_expression_sessions
				WHERE id = $1 AND user_id = $2
				FOR UPDATE
				""",
				session_id,
				user_id,
			)
			if not session:
				return None

			stats = await conn.fetchrow(
				"""
				SELECT AVG(heart_rate_bpm)::float AS avg_hr,
				       MAX(heart_rate_bpm)::float AS peak_hr,
				       AVG(stress_inference)::float AS avg_stress,
				       COUNT(*) AS samples
				FROM stress_expression_metrics
				WHERE session_id = $1
				""",
				session_id,
			)

			meta_update = metadata or {}
			if stats:
				meta_update = {**meta_update, "session_stats": {k: stats[k] for k in ("avg_hr", "peak_hr", "avg_stress", "samples")}}

			row = await conn.fetchrow(
				"""
				UPDATE stress_expression_sessions
				SET completed_at = COALESCE(completed_at, now()),
				    status = 'completed',
				    metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb
				WHERE id = $1 AND user_id = $2
				RETURNING id, user_id, started_at, completed_at, capture_type, status, metadata
				""",
				session_id,
				user_id,
				meta_update,
			)

	result = dict(row) if row else None
	if not result:
		return None
	result["samples"] = stats["samples"] if stats else 0
	result["avg_heart_rate"] = stats["avg_hr"] if stats else None
	result["avg_stress_inference"] = stats["avg_stress"] if stats else None
	result["peak_heart_rate"] = stats["peak_hr"] if stats else None
	return result


async def get_expression_session(
	user_id: int,
	session_id: int,
	*,
	include_metrics: bool = False,
	limit: int = 100,
	offset: int = 0,
) -> dict[str, Any] | None:
	async with db_session() as conn:
		session = await conn.fetchrow(
			"""
			SELECT id, user_id, started_at, completed_at, capture_type, status, metadata, device_capabilities
			FROM stress_expression_sessions
			WHERE id = $1 AND user_id = $2
			""",
			session_id,
			user_id,
		)
		if not session:
			return None
		stats = await conn.fetchrow(
			"""
			SELECT AVG(heart_rate_bpm)::float AS avg_hr,
			       MAX(heart_rate_bpm)::float AS peak_hr,
			       AVG(stress_inference)::float AS avg_stress,
			       COUNT(*) AS samples
			FROM stress_expression_metrics
			WHERE session_id = $1
			""",
			session_id,
		)
		metrics: list[dict[str, Any]] | None = None
		if include_metrics:
			metric_rows = await conn.fetch(
				"""
				SELECT captured_at, heart_rate_bpm, systolic_bp, diastolic_bp, breathing_rate,
				       expression_primary, expression_confidence, stress_inference, metadata
				FROM stress_expression_metrics
				WHERE session_id = $1
				ORDER BY captured_at
				LIMIT $2 OFFSET $3
				""",
				session_id,
				limit,
				offset,
			)
			metrics = [dict(row) for row in metric_rows]

	result = dict(session)
	result["samples"] = stats["samples"] if stats else 0
	result["avg_heart_rate"] = stats["avg_hr"] if stats else None
	result["avg_stress_inference"] = stats["avg_stress"] if stats else None
	result["peak_heart_rate"] = stats["peak_hr"] if stats else None
	if metrics is not None:
		result["metrics"] = metrics
	return result


async def list_insights(
	user_id: int,
	*,
	statuses: Sequence[str] | None = None,
	insight_types: Sequence[str] | None = None,
	days: int | None = None,
	limit: int = 20,
	offset: int = 0,
) -> tuple[list[dict[str, Any]], int | None]:
	clauses = ["user_id = $1"]
	params: list[Any] = [user_id]
	if statuses:
		clauses.append(f"status = ANY(${len(params)+1})")
		params.append([s.strip().lower() for s in statuses])
	if insight_types:
		clauses.append(f"insight_type = ANY(${len(params)+1})")
		params.append([t.strip().lower() for t in insight_types])
	if days:
		clauses.append(f"created_at >= now() - ${len(params)+1}::interval")
		params.append(f"{days} days")
	where_clause = " AND ".join(clauses)
	query = f"SELECT id, user_id, insight_type, severity, title, description, suggested_action, status, related_stressor_id, first_detected_at, last_occurrence_at, metadata, created_at, updated_at FROM stress_insights WHERE {where_clause} ORDER BY created_at DESC LIMIT ${len(params)+1} OFFSET ${len(params)+2}"
	params.extend([limit, offset])
	async with db_session() as conn:
		rows = await conn.fetch(query, *params)
	items = [dict(row) for row in rows]
	next_offset = offset + len(items) if len(items) == limit else None
	return items, next_offset


async def update_insight_status(user_id: int, insight_id: int, status: str) -> dict[str, Any] | None:
	async with db_session() as conn:
		row = await conn.fetchrow(
			"""
			UPDATE stress_insights
			SET status = $3, updated_at = now()
			WHERE id = $1 AND user_id = $2
			RETURNING id, user_id, insight_type, severity, title, description, suggested_action, status, related_stressor_id, first_detected_at, last_occurrence_at, metadata, created_at, updated_at
			""",
			insight_id,
			user_id,
			status,
		)
	return dict(row) if row else None
