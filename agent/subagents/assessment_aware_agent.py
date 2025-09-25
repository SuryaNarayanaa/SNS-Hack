"""Assessment-aware agent that delivers personalized support using standardized mental health assessments."""

from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from ..prompts import ASSESSMENT_AWARE_AGENT_PROMPT
from ..utils import get_last_user_message, get_recent_conversation_history
from assessments import get_user_assessments


async def _fetch_latest_assessments(user_id: int) -> Dict[str, Any]:
    """Collect latest assessment data for PHQ-9, GAD-7, and C-SSRS."""
    summary: Dict[str, Any] = {
        "recent_assessments": {},
        "severity_summary": {},
        "risk_flags": [],
        "recommendations": [],
    }

    records = await get_user_assessments(user_id)
    for record in records:
        assessment_type = record["assessment_type"]
        if assessment_type not in summary["recent_assessments"]:
            summary["recent_assessments"][assessment_type] = {
                "score": record["total_score"],
                "severity": record["severity_level"],
                "completed_at": record["completed_at"].isoformat() if record["completed_at"] else None,
                "recommendations": record.get("recommendations"),
            }
            summary["severity_summary"][assessment_type] = record["severity_level"]
            if record.get("risk_flags"):
                flags = json.loads(record["risk_flags"]) if isinstance(record["risk_flags"], str) else record["risk_flags"]
                summary["risk_flags"].extend(flags)
            if record.get("recommendations"):
                summary["recommendations"].append(f"{assessment_type}: {record['recommendations']}")

    return summary


def _determine_overall_risk(severity_summary: Dict[str, str], risk_flags: list[str]) -> str:
    if any(flag in {"suicide_plan", "suicide_behavior"} for flag in risk_flags):
        return "imminent"
    if any(flag in {"suicide_intent", "suicide_method"} for flag in risk_flags):
        return "high"
    if any("severe" in level or "high" in level for level in severity_summary.values()):
        return "high"
    if any("moderate" in level for level in severity_summary.values()):
        return "moderate"
    if any("mild" in level for level in severity_summary.values()):
        return "mild"
    return "low"


async def assessment_aware_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    user_message = get_last_user_message(state["messages"])
    conversation_history = get_recent_conversation_history(state["messages"])
    user_context = state.get("user_context", "")
    auth_user = state.get("extra_state", {}).get("auth_user")

    if not auth_user or "id" not in auth_user:
        fallback = AIMessage(
            content="I'm here for you. I don't have access to your assessment history right now, but we can still work through what you're experiencing together. How have things been lately?",
            additional_kwargs={"agent": "assessment_aware", "assessment_context": "unavailable"},
        )
        return {"messages": state["messages"] + [fallback]}

    assessment_summary = await _fetch_latest_assessments(auth_user["id"])

    prompt = ChatPromptTemplate.from_template(ASSESSMENT_AWARE_AGENT_PROMPT)
    formatted = prompt.format(
        user_context=user_context,
        conversation_history=conversation_history,
        user_message=user_message,
        assessment_summary=json.dumps(assessment_summary, ensure_ascii=False),
        risk_flags=assessment_summary["risk_flags"],
        severity_levels=assessment_summary["severity_summary"],
    )

    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.3)
    response = llm.invoke([{"role": "user", "content": formatted}])

    overall_risk = _determine_overall_risk(
        assessment_summary["severity_summary"], assessment_summary["risk_flags"]
    )

    ai_message = AIMessage(
        content=response.content,
        additional_kwargs={
            "agent": "assessment_aware",
            "assessment_informed": bool(assessment_summary["recent_assessments"]),
            "overall_risk": overall_risk,
            "risk_flags": assessment_summary["risk_flags"],
        },
    )

    return {"messages": state["messages"] + [ai_message]}
