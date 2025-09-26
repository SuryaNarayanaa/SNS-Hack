"""Utility to regenerate the expanded mock dataset used by load_mock_data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "src" / "mock_data.json"
DAYS_OF_DATA = 45

GOAL_CODES = [
    "reduce_stress",
    "sleep_better",
    "focus_better",
    "calm_evening",
    "build_resilience",
]
SESSION_TYPES = ["breathing", "mindfulness", "body_scan"]
TAGS = [
    ["morning", "stress"],
    ["evening", "relax"],
    ["work", "focus"],
    ["bedtime", "sleep"],
]
NOTES = [
    "Felt grounded",
    "Improved focus",
    "Let go of tension",
    "Calm before bed",
    "Reset mindset",
]
USER_MESSAGES = [
    ("I'm feeling overwhelmed today", "stress", -0.4),
    ("Energy is a bit low", "mood", -0.1),
    ("Feeling hopeful about progress", "reflection", 0.4),
    ("Struggling to wind down", "sleep", -0.2),
    ("I'm proud of sticking with it", "positive", 0.6),
]
AGENT_REPLIES = [
    ("Let's slow the breath together", "intervention", 0.2),
    ("Here is a quick grounding exercise", "support", 0.3),
    ("Celebrate this win—what worked?", "reinforce", 0.5),
    ("Try a gentle body scan before bed", "coaching", 0.3),
    ("Your consistency is inspiring", "encouragement", 0.6),
]
QUALITY_LABELS = [
    (90, "Excellent"),
    (85, "Great"),
    (80, "Good"),
    (75, "Fair"),
    (0, "Needs Attention"),
]
MOOD_LABELS = {
    1: "Very Low",
    2: "Low",
    3: "Neutral",
    4: "Positive",
    5: "Very Positive",
}
STRESS_LABELS = {
    1: "Minimal",
    2: "Mild",
    3: "Moderate",
    4: "Elevated",
}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pick(seq: Iterable, index: int):
    seq_list = list(seq)
    return seq_list[index % len(seq_list)]


@dataclass
class SessionConfig:
    exercise_type: str
    goal_code: str
    planned_duration: int


def make_mindfulness_sessions() -> tuple[list[dict], list[dict]]:
    sessions: list[dict] = []
    events: list[dict] = []
    base = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)

    for day in range(DAYS_OF_DATA):
        exercise = pick(SESSION_TYPES, day)
        goal = pick(GOAL_CODES, day)
        planned = [600, 900, 1200, 1500][day % 4]
        actual = planned - (day % 6) * 10
        start = base + timedelta(days=day)
        end = start + timedelta(seconds=actual)

        session = {
            "exercise_type": exercise,
            "goal_code": goal,
            "planned_duration_seconds": planned,
            "actual_duration_seconds": actual,
            "start_at": iso(start),
            "end_at": iso(end),
            "score_restful": None,
            "score_focus": None,
            "tags": pick(TAGS, day),
            "metadata": {"note": pick(NOTES, day)},
        }

        if exercise in {"breathing", "body_scan"}:
            session["score_restful"] = round(80 + (day % 11) + (0.5 if day % 2 else 0), 1)
        else:
            session["score_focus"] = round(84 + (day % 9) + (0.5 if day % 3 == 0 else 0), 1)

        sessions.append(session)

        event_template = {
            "session_index": day,
            "event_type": "breath_cycle",
            "numeric_value": round(5.5 + (day % 6) * 0.5, 1),
            "text_value": None,
            "occurred_at": iso(start + timedelta(minutes=3)),
        }
        if exercise == "mindfulness":
            event_template.update({
                "event_type": "pause",
                "numeric_value": None,
                "text_value": "Checked-in",
                "occurred_at": iso(start + timedelta(minutes=5)),
            })
        elif exercise == "body_scan":
            event_template.update({
                "event_type": "body_scan_segment",
                "numeric_value": None,
                "text_value": "Upper body relax",
                "occurred_at": iso(start + timedelta(minutes=7)),
            })
        events.append(event_template)

    return sessions, events


def quality_from_score(score: float) -> str:
    for threshold, label in QUALITY_LABELS:
        if score >= threshold:
            return label
    return QUALITY_LABELS[-1][1]


def make_sleep_sessions() -> tuple[list[dict], list[dict]]:
    sessions: list[dict] = []
    stages: list[dict] = []
    base = datetime(2024, 12, 31, 22, 0, tzinfo=timezone.utc)

    for day in range(DAYS_OF_DATA):
        start = base + timedelta(days=day)
        light_minutes = 240 + (day % 10) * 3
        deep_minutes = 90 + (day % 5) * 4
        rem_minutes = 110 + (day % 7) * 3
        awake_minutes = 20 + (day % 4) * 2
        total_minutes = light_minutes + deep_minutes + rem_minutes + awake_minutes
        time_in_bed = total_minutes + 15
        end = start + timedelta(minutes=time_in_bed)

        score = round(82 + (day % 9) - (0.3 if day % 6 == 0 else 0), 1)
        session = {
            "start_at": iso(start),
            "end_at": iso(end),
            "in_bed_start_at": iso(start + timedelta(minutes=5)),
            "in_bed_end_at": iso(end - timedelta(minutes=5)),
            "total_duration_minutes": round(float(total_minutes), 2),
            "time_in_bed_minutes": round(float(time_in_bed), 2),
            "sleep_efficiency": round(total_minutes / time_in_bed, 2),
            "latency_minutes": 10 + (day % 5) * 2,
            "awakenings_count": day % 3,
            "rem_minutes": rem_minutes,
            "deep_minutes": deep_minutes,
            "light_minutes": light_minutes,
            "awake_minutes": awake_minutes,
            "heart_rate_avg": 60 + (day % 7),
            "score_overall": score,
            "quality_label": quality_from_score(score),
            "device_source": "app",
            "metadata": {"note": pick(NOTES, day)},
        }
        sessions.append(session)

        current = start + timedelta(minutes=15)
        for stage_name, minutes, movement in (
            ("light", light_minutes, 0.15 + (day % 5) * 0.01),
            ("deep", deep_minutes, 0.08 + (day % 4) * 0.01),
            ("rem", rem_minutes, 0.05 + (day % 3) * 0.01),
        ):
            stages.append(
                {
                    "session_index": day,
                    "stage": stage_name,
                    "start_at": iso(current),
                    "end_at": iso(current + timedelta(minutes=minutes)),
                    "duration_seconds": int(minutes * 60),
                    "movement_index": round(movement, 3),
                }
            )
            current += timedelta(minutes=minutes)

    return sessions, stages


def make_mood_entries() -> list[dict]:
    entries: list[dict] = []
    base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    for day in range(DAYS_OF_DATA):
        mood_value = 1 + (day % 5)
        entries.append(
            {
                "mood_value": mood_value,
                "mood_label": MOOD_LABELS[mood_value],
                "note": pick(NOTES, day),
                "improvement_flag": mood_value >= 4,
                "created_at": iso(base + timedelta(days=day)),
            }
        )
    return entries


def make_stress_assessments() -> list[dict]:
    assessments: list[dict] = []
    base = datetime(2025, 1, 1, 14, 0, tzinfo=timezone.utc)
    for day in range(DAYS_OF_DATA):
        score = 1 + (day % 4)
        assessments.append(
            {
                "score": score,
                "qualitative_label": STRESS_LABELS[score],
                "context_note": pick(NOTES, day),
                "created_at": iso(base + timedelta(days=day)),
            }
        )
    return assessments


def make_behavioral_events(moods: list[dict], stress: list[dict]) -> list[dict]:
    events: list[dict] = []
    for mood in moods:
        events.append(
            {
                "event_type": "mood_rating",
                "numeric_value": round(mood["mood_value"] / 5, 2),
                "occurred_at": mood["created_at"],
            }
        )
    for item in stress:
        events.append(
            {
                "event_type": "stress_rating",
                "numeric_value": round(item["score"] / 4, 2),
                "occurred_at": item["created_at"],
            }
        )
    events.sort(key=lambda e: e["occurred_at"])
    return events


def make_conversation_behavior() -> list[dict]:
    messages: list[dict] = []
    base = datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc)
    for day in range(DAYS_OF_DATA):
        user_msg, intent, sentiment = pick(USER_MESSAGES, day)
        agent_msg, agent_intent, agent_sentiment = pick(AGENT_REPLIES, day)
        user_time = base + timedelta(days=day)
        agent_time = user_time + timedelta(minutes=1)
        messages.extend(
            [
                {
                    "role": "user",
                    "content": user_msg,
                    "intent": intent,
                    "sentiment": sentiment,
                    "occurred_at": iso(user_time),
                },
                {
                    "role": "agent",
                    "content": agent_msg,
                    "intent": agent_intent,
                    "sentiment": agent_sentiment,
                    "occurred_at": iso(agent_time),
                },
            ]
        )
    return messages


def main() -> None:
    mindfulness_sessions, mindfulness_events = make_mindfulness_sessions()
    sleep_sessions, sleep_stages = make_sleep_sessions()
    mood_entries = make_mood_entries()
    stress_assessments = make_stress_assessments()
    behavioral_events = make_behavioral_events(mood_entries, stress_assessments)
    conversation_behavior = make_conversation_behavior()

    payload = {
        "mindfulness_sessions": mindfulness_sessions,
        "mindfulness_session_events": mindfulness_events,
        "sleep_sessions": sleep_sessions,
        "sleep_stages": sleep_stages,
        "mood_entries": mood_entries,
        "stress_assessments": stress_assessments,
        "behavioral_events": behavioral_events,
        "conversation_behavior": conversation_behavior,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote dataset with {len(mindfulness_sessions)} mindfulness sessions to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
