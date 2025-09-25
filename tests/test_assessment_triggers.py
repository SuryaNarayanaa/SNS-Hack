from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.utils import assessment_triggers
from agent.utils.assessments import AssessmentType

from tests.stubs import StubConnection


def test_analyze_message_for_assessments_detects_multiple():
    message = "I'm feeling depressed and anxious, sometimes I even think about how I might end my life."

    triggers = assessment_triggers.analyze_message_for_assessments(message)

    trigger_types = {trigger[0] for trigger in triggers}
    assert AssessmentType.PHQ9 in trigger_types
    assert AssessmentType.GAD7 in trigger_types
    assert AssessmentType.COLUMBIA in trigger_types


@pytest.mark.asyncio
async def test_should_trigger_assessment_when_due(monkeypatch, make_db_session, frozen_now):
    async def fake_due(user_id: int):
        return [AssessmentType.PHQ9]

    monkeypatch.setattr(assessment_triggers, "check_due_assessments", fake_due)

    fake_conn = StubConnection(fetchrow_results=None)
    make_db_session(assessment_triggers, fake_conn)

    should_trigger = await assessment_triggers.should_trigger_assessment(
        user_id=1,
        assessment_type=AssessmentType.PHQ9,
        trigger_reason="depressive_symptoms_detected",
        severity_score=1,
    )

    assert should_trigger is True


@pytest.mark.asyncio
async def test_should_trigger_assessment_respects_cooldown(monkeypatch, make_db_session):
    async def fake_due(user_id: int):
        return []

    monkeypatch.setattr(assessment_triggers, "check_due_assessments", fake_due)

    now = datetime.now(timezone.utc)
    last_completed = now - timedelta(days=2)
    next_due = now + timedelta(days=5)
    fake_conn = StubConnection(
        fetchrow_results=[
            {
                "completed_at": last_completed,
                "next_assessment_due": next_due,
                "triggered_by": "depressive_symptoms_detected",
            }
        ]
    )
    make_db_session(assessment_triggers, fake_conn)

    should_trigger = await assessment_triggers.should_trigger_assessment(
        user_id=1,
        assessment_type=AssessmentType.PHQ9,
        trigger_reason="depressive_symptoms_detected",
        severity_score=1,
    )

    assert should_trigger is False


@pytest.mark.asyncio
async def test_should_trigger_assessment_high_severity(monkeypatch, make_db_session, frozen_now):
    async def fake_due(user_id: int):
        return []

    monkeypatch.setattr(assessment_triggers, "check_due_assessments", fake_due)

    fake_conn = StubConnection(
        fetchrow_results=[
            {
                "completed_at": frozen_now,
                "next_assessment_due": frozen_now + timedelta(days=10),
                "triggered_by": "previous_reason",
            }
        ]
    )
    make_db_session(assessment_triggers, fake_conn)

    should_trigger = await assessment_triggers.should_trigger_assessment(
        user_id=1,
        assessment_type=AssessmentType.COLUMBIA,
        trigger_reason="suicidality_language_detected",
        severity_score=4,
    )

    assert should_trigger is True