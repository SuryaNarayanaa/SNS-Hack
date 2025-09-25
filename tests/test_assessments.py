from __future__ import annotations

from datetime import timedelta

import json
import pytest

import assessments
from assessments import (
    AssessmentResponse,
    AssessmentResult,
    AssessmentType,
    check_due_assessments,
    get_user_assessments,
    process_assessment,
    save_assessment_result,
)

from tests.stubs import StubConnection


def _all_responses(question_ids: list[str], score: int = 0) -> list[AssessmentResponse]:
    return [AssessmentResponse(question_id=qid, score=score) for qid in question_ids]


def test_process_assessment_phq9_minimal(patch_now, frozen_now):
    patch_now(assessments, frozen_now)
    responses = _all_responses(sorted({item["id"] for item in assessments.PHQ9_QUESTIONS}))

    result = process_assessment(AssessmentType.PHQ9, responses)

    assert result.total_score == 0
    assert result.severity_level == "minimal_depression"
    assert result.risk_flags == []
    assert result.next_assessment_due == frozen_now + timedelta(days=60)


def test_process_assessment_missing_answer_raises(patch_now, frozen_now):
    patch_now(assessments, frozen_now)
    responses = _all_responses(sorted({item["id"] for item in assessments.PHQ9_QUESTIONS}))
    responses.pop()

    with pytest.raises(ValueError, match="Missing responses"):
        process_assessment(AssessmentType.PHQ9, responses)


def test_process_assessment_columbia_risk_flags(patch_now, frozen_now):
    patch_now(assessments, frozen_now)
    responses = [
        AssessmentResponse(question_id="cssrs_q1", score=1),
        AssessmentResponse(question_id="cssrs_q2", score=1),
        AssessmentResponse(question_id="cssrs_q3", score=1),
        AssessmentResponse(question_id="cssrs_q4", score=1),
        AssessmentResponse(question_id="cssrs_q5", score=1),
        AssessmentResponse(question_id="cssrs_q6", score=0),
    ]

    result = process_assessment(AssessmentType.COLUMBIA, responses)

    assert result.severity_level == "high_suicide_risk"
    assert "suicide_intent" in result.risk_flags
    assert result.next_assessment_due == frozen_now + timedelta(days=2)


@pytest.mark.asyncio
async def test_save_assessment_result_persists(make_db_session, frozen_now):
    result = AssessmentResult(
        total_score=9,
        severity_level="mild_depression",
        risk_flags=["suicide_ideation"],
        recommendations=["Follow up"],
        next_assessment_due=frozen_now + timedelta(days=30),
    )
    responses = _all_responses(sorted({item["id"] for item in assessments.PHQ9_QUESTIONS}), score=1)

    fake_conn = StubConnection(fetchrow_results={"id": 42})
    make_db_session(assessments, fake_conn)

    saved_id = await save_assessment_result(1, AssessmentType.PHQ9, "auto", responses, result)

    assert saved_id == 42
    assert fake_conn.fetchrow_calls
    query, params = fake_conn.fetchrow_calls[0]
    assert "INSERT INTO mental_health_assessments" in query
    assert params[0] == 1
    assert params[1] == AssessmentType.PHQ9.value
    assert json.loads(params[3])[0]["question_id"].startswith("phq9_")
    assert fake_conn.closed


@pytest.mark.asyncio
async def test_get_user_assessments_parses_json(make_db_session, frozen_now):
    stored_responses = json.dumps([{"question_id": "phq9_q1", "score": 2}])
    stored_flags = json.dumps(["flag"])
    stored_recs = json.dumps(["rec"])
    fake_conn = StubConnection(
        fetch_results=[
            [
                {
                    "id": 1,
                    "assessment_type": AssessmentType.PHQ9.value,
                    "triggered_by": "auto",
                    "responses": stored_responses,
                    "total_score": 5,
                    "severity_level": "mild_depression",
                    "risk_flags": stored_flags,
                    "recommendations": stored_recs,
                    "next_assessment_due": frozen_now + timedelta(days=30),
                    "completed_at": frozen_now,
                    "created_at": frozen_now,
                }
            ]
        ]
    )
    make_db_session(assessments, fake_conn)

    results = await get_user_assessments(1, AssessmentType.PHQ9, limit=5)

    assert len(results) == 1
    record = results[0]
    assert record["risk_flags"] == ["flag"]
    assert record["recommendations"] == ["rec"]
    assert record["responses"][0]["question_id"] == "phq9_q1"


@pytest.mark.asyncio
async def test_check_due_assessments_filters_future(make_db_session, frozen_now, patch_now):
    patch_now(assessments, frozen_now)
    fake_conn = StubConnection(
        fetch_results=[
            [
                {
                    "assessment_type": AssessmentType.PHQ9.value,
                    "next_assessment_due": frozen_now + timedelta(days=10),
                },
                {
                    "assessment_type": AssessmentType.GAD7.value,
                    "next_assessment_due": frozen_now - timedelta(days=1),
                },
            ]
        ]
    )
    make_db_session(assessments, fake_conn)

    due = await check_due_assessments(1)

    assert AssessmentType.GAD7 in due
    assert AssessmentType.PHQ9 not in due
    assert AssessmentType.COLUMBIA in due