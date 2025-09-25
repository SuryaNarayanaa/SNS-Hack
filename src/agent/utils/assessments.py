"""Standardised mental health assessments and persistence helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Sequence

import asyncpg
from pydantic import BaseModel, Field

from db import db_session


class AssessmentType(str, Enum):
    PHQ9 = "phq9"
    GAD7 = "gad7"
    COLUMBIA = "columbia"


class AssessmentResponse(BaseModel):
    """Single response supplied for an assessment question."""

    question_id: str = Field(..., min_length=1)
    score: int = Field(..., ge=0)
    answer: str | None = None


@dataclass
class AssessmentResult:
    total_score: int
    severity_level: str
    risk_flags: List[str]
    recommendations: List[str]
    next_assessment_due: datetime


Question = Dict[str, Any]


STANDARD_FREQUENCY_DAYS = {
    AssessmentType.PHQ9: 30,
    AssessmentType.GAD7: 30,
    AssessmentType.COLUMBIA: 7,
}


PHQ9_CHOICES = [
    {"label": "Not at all", "value": 0},
    {"label": "Several days", "value": 1},
    {"label": "More than half the days", "value": 2},
    {"label": "Nearly every day", "value": 3},
]


PHQ9_QUESTIONS: List[Question] = [
    {
        "id": "phq9_q1",
        "prompt": "Little interest or pleasure in doing things?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q2",
        "prompt": "Feeling down, depressed, or hopeless?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q3",
        "prompt": "Trouble falling or staying asleep, or sleeping too much?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q4",
        "prompt": "Feeling tired or having little energy?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q5",
        "prompt": "Poor appetite or overeating?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q6",
        "prompt": "Feeling bad about yourself — or that you are a failure or have let yourself or your family down?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q7",
        "prompt": "Trouble concentrating on things, such as reading the newspaper or watching television?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q8",
        "prompt": "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual?",
        "choices": PHQ9_CHOICES,
    },
    {
        "id": "phq9_q9",
        "prompt": "Thoughts that you would be better off dead, or of hurting yourself in some way?",
        "choices": PHQ9_CHOICES,
    },
]


GAD7_CHOICES = [
    {"label": "Not at all", "value": 0},
    {"label": "Several days", "value": 1},
    {"label": "More than half the days", "value": 2},
    {"label": "Nearly every day", "value": 3},
]


GAD7_QUESTIONS: List[Question] = [
    {
        "id": "gad7_q1",
        "prompt": "Feeling nervous, anxious, or on edge?",
        "choices": GAD7_CHOICES,
    },
    {
        "id": "gad7_q2",
        "prompt": "Not being able to stop or control worrying?",
        "choices": GAD7_CHOICES,
    },
    {
        "id": "gad7_q3",
        "prompt": "Worrying too much about different things?",
        "choices": GAD7_CHOICES,
    },
    {
        "id": "gad7_q4",
        "prompt": "Trouble relaxing?",
        "choices": GAD7_CHOICES,
    },
    {
        "id": "gad7_q5",
        "prompt": "Being so restless that it's hard to sit still?",
        "choices": GAD7_CHOICES,
    },
    {
        "id": "gad7_q6",
        "prompt": "Becoming easily annoyed or irritable?",
        "choices": GAD7_CHOICES,
    },
    {
        "id": "gad7_q7",
        "prompt": "Feeling afraid as if something awful might happen?",
        "choices": GAD7_CHOICES,
    },
]


COLUMBIA_CHOICES = [
    {"label": "No", "value": 0},
    {"label": "Yes", "value": 1},
]


COLUMBIA_QUESTIONS: List[Question] = [
    {
        "id": "cssrs_q1",
        "prompt": "Have you wished you were dead or wished you could go to sleep and not wake up?",
        "choices": COLUMBIA_CHOICES,
    },
    {
        "id": "cssrs_q2",
        "prompt": "Have you had any actual thoughts of killing yourself?",
        "choices": COLUMBIA_CHOICES,
    },
    {
        "id": "cssrs_q3",
        "prompt": "Have you been thinking about how you might do this?",
        "choices": COLUMBIA_CHOICES,
    },
    {
        "id": "cssrs_q4",
        "prompt": "Have you had these thoughts and had some intention of acting on them?",
        "choices": COLUMBIA_CHOICES,
    },
    {
        "id": "cssrs_q5",
        "prompt": "Have you started to work out or worked out the details of how to kill yourself? Do you intend to carry out this plan?",
        "choices": COLUMBIA_CHOICES,
    },
    {
        "id": "cssrs_q6",
        "prompt": "Have you done anything, started to do anything, or prepared to do anything to end your life?",
        "choices": COLUMBIA_CHOICES,
    },
]


QUESTION_MAP = {
    AssessmentType.PHQ9: {item["id"] for item in PHQ9_QUESTIONS},
    AssessmentType.GAD7: {item["id"] for item in GAD7_QUESTIONS},
    AssessmentType.COLUMBIA: {item["id"] for item in COLUMBIA_QUESTIONS},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_responses(assessment_type: AssessmentType, responses: Sequence[AssessmentResponse]) -> None:
    expected_ids = QUESTION_MAP[assessment_type]
    from collections import Counter

    provided_ids = [response.question_id for response in responses]

    missing = expected_ids - set(provided_ids)
    if missing:
        raise ValueError(f"Missing responses for questions: {sorted(missing)}")

    duplicates = [item for item, count in Counter(provided_ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate responses detected: {duplicates}")


def _score_phq9(responses: Sequence[AssessmentResponse]) -> AssessmentResult:
    total = sum(response.score for response in responses)

    if total <= 4:
        severity = "minimal_depression"
        interval = 60
        recommendations = ["Maintain current coping strategies and continue monitoring mood weekly."]
    elif total <= 9:
        severity = "mild_depression"
        interval = 45
        recommendations = ["Consider behavioural activation exercises and follow-up within 6 weeks."]
    elif total <= 14:
        severity = "moderate_depression"
        interval = 30
        recommendations = ["Schedule structured therapy check-in and reassess within a month."]
    elif total <= 19:
        severity = "moderately_severe_depression"
        interval = 21
        recommendations = [
            "Increase therapy frequency if possible and discuss pharmacotherapy options with a clinician.",
        ]
    else:
        severity = "severe_depression"
        interval = 14
        recommendations = [
            "Coordinate urgent clinical evaluation, ensure crisis resources are available, and reassess within two weeks.",
        ]

    risk_flags: List[str] = []
    suicide_item = next((resp for resp in responses if resp.question_id == "phq9_q9"), None)
    if suicide_item and suicide_item.score >= 1:
        risk_flags.append("suicide_ideation")
        if suicide_item.score >= 3:
            risk_flags.append("suicide_intent")

    next_due = _now() + timedelta(days=interval)
    return AssessmentResult(total, severity, risk_flags, recommendations, next_due)


def _score_gad7(responses: Sequence[AssessmentResponse]) -> AssessmentResult:
    total = sum(response.score for response in responses)

    if total <= 4:
        severity = "minimal_anxiety"
        interval = 60
        recommendations = ["Continue resilience strategies and monitor symptoms monthly."]
    elif total <= 9:
        severity = "mild_anxiety"
        interval = 45
        recommendations = ["Introduce relaxation and grounding techniques; follow-up in 4-6 weeks."]
    elif total <= 14:
        severity = "moderate_anxiety"
        interval = 30
        recommendations = ["Practice CBT-based worry logs and schedule therapy review within a month."]
    else:
        severity = "severe_anxiety"
        interval = 21
        recommendations = [
            "Escalate to clinician for medication review and intensive coping strategies; reassess in 3 weeks.",
        ]

    risk_flags: List[str] = []
    if total >= 15:
        risk_flags.append("severe_anxiety")

    next_due = _now() + timedelta(days=interval)
    return AssessmentResult(total, severity, risk_flags, recommendations, next_due)


def _score_columbia(responses: Sequence[AssessmentResponse]) -> AssessmentResult:
    score_map = {response.question_id: response.score for response in responses}

    total = sum(score_map.values())
    risk_flags: List[str] = []

    if score_map.get("cssrs_q6", 0) >= 1:
        severity = "imminent_suicide_risk"
        interval = 1
        risk_flags.append("suicide_behavior")
        recommendations = [
            "Activate emergency safety plan immediately and ensure direct clinical supervision.",
            "Contact crisis services or emergency responders if immediate support is unavailable.",
        ]
    elif score_map.get("cssrs_q5", 0) >= 1 or score_map.get("cssrs_q4", 0) >= 1:
        severity = "high_suicide_risk"
        interval = 2
        risk_flags.extend(["suicide_intent", "suicide_plan"])
        recommendations = [
            "Begin high-intensity monitoring, restrict access to means, and coordinate rapid clinician follow-up.",
        ]
    elif score_map.get("cssrs_q2", 0) >= 1 or score_map.get("cssrs_q3", 0) >= 1:
        severity = "moderate_suicide_risk"
        interval = 3
        risk_flags.append("suicide_ideation")
        recommendations = [
            "Create collaborative safety plan, increase contact frequency, and reassess within 72 hours.",
        ]
    elif score_map.get("cssrs_q1", 0) >= 1:
        severity = "low_suicide_risk"
        interval = 7
        recommendations = [
            "Provide crisis resources and encourage daily mood tracking; reassess within a week.",
        ]
    else:
        severity = "no_suicide_risk"
        interval = STANDARD_FREQUENCY_DAYS[AssessmentType.COLUMBIA]
        recommendations = ["Continue routine monitoring and reinforce protective factors."]

    next_due = _now() + timedelta(days=interval)
    return AssessmentResult(total, severity, risk_flags, recommendations, next_due)


SCORING_FUNCTIONS = {
    AssessmentType.PHQ9: _score_phq9,
    AssessmentType.GAD7: _score_gad7,
    AssessmentType.COLUMBIA: _score_columbia,
}


def process_assessment(
    assessment_type: AssessmentType,
    responses: Sequence[AssessmentResponse],
    triggered_by: str = "manual",
) -> AssessmentResult:
    """Validate and score an assessment submission."""

    if assessment_type not in SCORING_FUNCTIONS:
        raise ValueError(f"Unsupported assessment: {assessment_type}")

    _validate_responses(assessment_type, responses)
    return SCORING_FUNCTIONS[assessment_type](responses)


async def save_assessment_result(
    user_id: int,
    assessment_type: AssessmentType,
    triggered_by: str,
    responses: Sequence[AssessmentResponse],
    result: AssessmentResult,
) -> int:
    """Persist an assessment result and return its identifier."""

    serialised_responses = [response.model_dump() for response in responses]

    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mental_health_assessments (
                user_id,
                assessment_type,
                triggered_by,
                responses,
                total_score,
                severity_level,
                risk_flags,
                recommendations,
                next_assessment_due,
                completed_at
            ) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7::jsonb, $8, $9, NOW())
            RETURNING id
            """,
            user_id,
            assessment_type.value,
            triggered_by,
            json.dumps(serialised_responses, ensure_ascii=False),
            result.total_score,
            result.severity_level,
            json.dumps(result.risk_flags, ensure_ascii=False),
            json.dumps(result.recommendations, ensure_ascii=False),
            result.next_assessment_due,
        )

    return int(row["id"]) if row else -1


async def get_user_assessments(
    user_id: int,
    assessment_type: AssessmentType | None = None,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Return stored assessment history ordered by recency."""

    where_clause = ""
    params: List[Any] = [user_id]
    if assessment_type:
        where_clause = " AND assessment_type = $2"
        params.append(assessment_type.value)

    query = (
        "SELECT id, assessment_type, triggered_by, responses, total_score, severity_level, "
        "risk_flags, recommendations, next_assessment_due, completed_at, created_at "
        "FROM mental_health_assessments WHERE user_id = $1" + where_clause + " "
        "ORDER BY completed_at DESC NULLS LAST LIMIT $%d" % (len(params) + 1)
    )
    params.append(limit)

    async with db_session() as conn:
        records: Sequence[asyncpg.Record] = await conn.fetch(query, *params)

    results: List[Dict[str, Any]] = []
    for record in records:
        payload = dict(record)
        if payload.get("risk_flags"):
            try:
                payload["risk_flags"] = json.loads(payload["risk_flags"])
            except (TypeError, json.JSONDecodeError):
                payload["risk_flags"] = []
        else:
            payload["risk_flags"] = []

        if payload.get("recommendations"):
            try:
                payload["recommendations"] = json.loads(payload["recommendations"])
            except (TypeError, json.JSONDecodeError):
                payload["recommendations"] = [payload["recommendations"]]
        else:
            payload["recommendations"] = []

        if payload.get("responses"):
            try:
                payload["responses"] = json.loads(payload["responses"])
            except (TypeError, json.JSONDecodeError):
                payload["responses"] = []

        results.append(payload)

    return results


async def check_due_assessments(user_id: int) -> List[AssessmentType]:
    """Determine which assessments are due based on next_due timestamps."""

    now = _now()
    async with db_session() as conn:
        records = await conn.fetch(
            """
            SELECT DISTINCT ON (assessment_type) assessment_type, next_assessment_due
            FROM mental_health_assessments
            WHERE user_id = $1
            ORDER BY assessment_type, completed_at DESC NULLS LAST
            """,
            user_id,
        )

    latest_by_type = {record["assessment_type"]: record["next_assessment_due"] for record in records}

    due: List[AssessmentType] = []
    for assessment in AssessmentType:
        next_due = latest_by_type.get(assessment.value)
        if next_due is None or next_due <= now:
            due.append(assessment)

    return due
