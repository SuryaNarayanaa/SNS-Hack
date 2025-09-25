"""Heuristics for triggering mental health assessments from conversation context."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Tuple

from .assessments import AssessmentType, check_due_assessments
from db import db_session


Trigger = Tuple[AssessmentType, str, int | None]


PHQ9_PATTERNS: tuple[tuple[str, int], ...] = (
    (r"\b(depress(ed|ing)?|hopeless|worthless|empty)\b", 2),
    (r"\b(cannot|can't) enjoy\b", 2),
    (r"\b(fatigued?|exhausted?|tired all the time)\b", 1),
)


GAD7_PATTERNS: tuple[tuple[str, int], ...] = (
    (r"\b(anxiet(y|ies)|anxious|panic attack)\b", 2),
    (r"\b(worry|worried|overthink(ing)?)\b", 1),
    (r"\b(restless|on edge|nervous)\b", 1),
)


COLUMBIA_PATTERNS: tuple[tuple[str, int], ...] = (
    (r"\b(suicid(al|e)|kill myself|end my life)\b", 3),
    (r"\b(self[- ]harm|hurt myself on purpose)\b", 3),
    (r"\b(no reason to live|can't go on)\b", 2),
    (r"\b(i have a plan|worked out how to)\b", 4),
)


PATTERN_MAP = {
    AssessmentType.PHQ9: PHQ9_PATTERNS,
    AssessmentType.GAD7: GAD7_PATTERNS,
    AssessmentType.COLUMBIA: COLUMBIA_PATTERNS,
}


def _scan_message(patterns: Iterable[tuple[str, int]], message: str) -> int:
    score = 0
    for pattern, severity in patterns:
        if re.search(pattern, message):
            score = max(score, severity)
    return score


def analyze_message_for_assessments(message: str, user_id: int | None = None) -> List[Trigger]:
    """Return candidate assessments to trigger from a conversation snippet."""

    text = message.lower()
    triggers: List[Trigger] = []

    phq_score = _scan_message(PHQ9_PATTERNS, text)
    if phq_score:
        reason = "depressive_symptoms_detected"
        triggers.append((AssessmentType.PHQ9, reason, phq_score))

    gad_score = _scan_message(GAD7_PATTERNS, text)
    if gad_score:
        reason = "anxiety_symptoms_detected"
        triggers.append((AssessmentType.GAD7, reason, gad_score))

    columbia_score = _scan_message(COLUMBIA_PATTERNS, text)
    if columbia_score:
        reason = "suicidality_language_detected"
        triggers.append((AssessmentType.COLUMBIA, reason, columbia_score))

    return triggers


async def should_trigger_assessment(
    user_id: int,
    assessment_type: AssessmentType,
    trigger_reason: str,
    severity_score: int | None,
) -> bool:
    """Gate assessment triggers to prevent over-screening while staying safe."""

    now = datetime.now(timezone.utc)
    due_assessments = await check_due_assessments(user_id)
    if assessment_type in due_assessments:
        return True

    async with db_session() as conn:
        record = await conn.fetchrow(
            """
            SELECT completed_at, next_assessment_due, triggered_by
            FROM mental_health_assessments
            WHERE user_id = $1 AND assessment_type = $2
            ORDER BY completed_at DESC NULLS LAST
            LIMIT 1
            """,
            user_id,
            assessment_type.value,
        )

    if record is None:
        return True

    last_completed = record["completed_at"]
    next_due = record["next_assessment_due"]
    last_reason = record["triggered_by"]

    if next_due and next_due <= now:
        return True

    # Severity overrides
    if severity_score is not None and severity_score >= 4:
        return True

    if severity_score is not None and severity_score >= 3:
        if not last_completed or (now - last_completed) >= timedelta(days=3):
            return True

    if severity_score is not None and severity_score >= 2:
        if not last_completed or (now - last_completed) >= timedelta(days=7):
            return True

    cooldown_days = 14
    if severity_score is not None:
        cooldown_days = max(5, 14 - severity_score * 2)

    if not last_completed or (now - last_completed) >= timedelta(days=cooldown_days):
        return True

    if trigger_reason and trigger_reason != last_reason:
        # Allow a different trigger after a brief reflection period
        if not last_completed or (now - last_completed) >= timedelta(days=2):
            return True

    return False
