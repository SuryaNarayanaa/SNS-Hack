

"""FastAPI entry point for the SNS Hack backend."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from agent import supervisor
from auth import (
    DuplicateUserError,
    InvalidCredentialsError,
    authenticate_user,
    cleanup_expired_sessions,
    create_guest_session,
    create_session,
    create_user,
    get_user_by_token,
)
from db import (
    init_db,
    insert_behavioral_event,
    insert_conversation_message,
    create_conversation,
    update_conversation_stats,
    db_session,
)
from routes.sleep_routes import router as sleep_router
from routes.stress_routes import router as stress_router
from routes.mood_routes import router as mood_router

app = FastAPI(title="Neptune - Mental Healthcare App", version="0.2.0")
bearer_scheme = HTTPBearer(auto_error=False)

app.include_router(sleep_router)
app.include_router(stress_router)
app.include_router(mood_router)


from pydantic import EmailStr

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    is_guest: bool
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class RegisterRequest(BaseModel):
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GuestRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=32)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    user_context: str | None = None


# --- Telemetry / Behavioral Logging Schemas ---
class StartConversationIn(BaseModel):
    title: str | None = None
    metadata: dict | None = None


class TelemetryEventIn(BaseModel):
    event_type: str
    numeric_value: float | None = None
    text_value: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None
    occurred_at: datetime | None = None
    conversation_id: int | None = None


class TelemetryMessageIn(BaseModel):
    role: str  # 'user' | 'agent'
    content: str | None = None
    intent: str | None = None
    sentiment: float | None = None
    coping_action: str | None = None
    response_latency_ms: int | None = None
    metadata: dict | None = None
    conversation_id: int | None = None
    session_token: str | None = None


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    token = credentials.credentials
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    return user | {"token": token}


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    await cleanup_expired_sessions()


@app.get("/")
async def read_root() -> dict[str, str]:
    """Return a friendly greeting so callers know the service is alive."""
    return {"message": "Hello from sns-hack!"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic readiness probe for infrastructure monitors."""
    return {"status": "ok"}


@app.get("/diagram")
async def get_diagram() -> str:
    """Return the Mermaid diagram code for the supervisor graph."""
    return supervisor.get_graph().draw_mermaid()


@app.post("/auth/register", response_model=AuthResponse)
async def register(payload: RegisterRequest) -> AuthResponse:
    try:
        user = await create_user(payload.email, payload.password)
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    token, expires_at = await create_session(user["id"])
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserResponse(**user))


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    try:
        user = await authenticate_user(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    token, expires_at = await create_session(user["id"])
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserResponse(**user))


@app.post("/auth/guest", response_model=AuthResponse)
async def guest_login(payload: GuestRequest | None = None) -> AuthResponse:
    display_name = payload.display_name if payload else None
    token, user, expires_at = await create_guest_session(display_name)
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserResponse(**user))


@app.post("/chat")
async def chat(payload: ChatRequest, current_user: dict[str, Any] = Depends(get_current_user)) -> StreamingResponse:
    """Stream a chat response from the LangGraph supervisor agent."""

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_context": payload.user_context or "No additional context provided.",
        "extra_state": {"auth_user": {key: current_user[key] for key in ("id", "email", "is_guest", "token") if key in current_user}},
    }

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    async def generate_response():
        async for event in supervisor.astream_events(initial_state, config=config, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk_data = event["data"].get("chunk")
                if chunk_data and hasattr(chunk_data, "content"):
                    chunk = chunk_data.content
                    if chunk:
                        yield f"data: {chunk}\n\n"
            elif event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                yield "data: [DONE]\n\n"
                break

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------- Telemetry Endpoints (Testing & Analytics) -----------------

@app.post("/telemetry/start_conversation")
async def start_conversation(
    payload: StartConversationIn,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    convo_id = await create_conversation(
        current_user["id"],
        session_token=current_user.get("token"),
        title=payload.title,
        metadata=payload.metadata,
    )
    return {"conversation_id": convo_id}


@app.post("/telemetry/event")
async def log_behavioral_event(
    payload: TelemetryEventIn,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    await insert_behavioral_event(
        current_user["id"],
        payload.event_type,
        numeric_value=payload.numeric_value,
        text_value=payload.text_value,
        tags=payload.tags,
        metadata=payload.metadata,
        session_token=current_user.get("token"),
        occurred_at=payload.occurred_at.isoformat() if payload.occurred_at else None,
    )
    return {"status": "ok"}


@app.post("/telemetry/message")
async def log_conversation_message(
    payload: TelemetryMessageIn,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    await insert_conversation_message(
        current_user["id"],
        role=payload.role,
        content=payload.content,
        intent=payload.intent,
        sentiment=payload.sentiment,
        coping_action=payload.coping_action,
        response_latency_ms=payload.response_latency_ms,
        metadata=payload.metadata,
        session_token=payload.session_token or current_user.get("token"),
        conversation_id=payload.conversation_id,
    )
    if payload.conversation_id:
        await update_conversation_stats(payload.conversation_id, increment_messages=1)
    return {"status": "ok"}


@app.patch("/telemetry/conversation/{conversation_id}/end")
async def end_conversation(
    conversation_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    await update_conversation_stats(conversation_id, end=True)
    return {"status": "ended", "conversation_id": conversation_id}


@app.get("/telemetry/behavioral_events")
async def list_behavioral_events(
    limit: int = 50,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    async with db_session() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, numeric_value, text_value, tags, metadata, occurred_at
            FROM behavioral_events
            WHERE user_id = $1
            ORDER BY occurred_at DESC
            LIMIT $2
            """,
            current_user["id"],
            limit,
        )
    return {"items": [dict(r) for r in rows]}


@app.get("/telemetry/conversation_messages")
async def list_conversation_messages(
    limit: int = 50,
    current_user: dict[str, Any] = Depends(get_current_user),
):
    async with db_session() as conn:
        rows = await conn.fetch(
            """
            SELECT id, role, intent, sentiment, coping_action, conversation_id, occurred_at
            FROM conversation_behavior
            WHERE user_id = $1
            ORDER BY occurred_at DESC
            LIMIT $2
            """,
            current_user["id"],
            limit,
        )
    return {"items": [dict(r) for r in rows]}


def main() -> None:
    """Run a development server when executed as a module."""

    port = int(os.getenv("PORT", "8000"))

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=os.getenv("UVICORN_RELOAD", "true").lower() == "true")


if __name__ == "__main__":
    main()

# ---------------- Analytics Endpoints (Aggregated Views) -----------------

# Placed after __main__ guard so they are defined at import; harmless ordering.

@app.get("/analytics/daily-scores")
async def analytics_daily_scores(
    days: int = Query(30, ge=1, le=180),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """Return per-day average numeric scores for *rating events (mood/stress/etc.).

    Falls back to empty list if the continuous aggregate view is absent.
    """
    async with db_session() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT day, event_type, avg_score, samples
                FROM daily_behavior_scores
                WHERE user_id = $1
                  AND day >= (now() - $2::interval)
                ORDER BY day, event_type
                """,
                current_user["id"],
                f"{days} days",
            )
        except Exception:
            rows = []
    return {"items": [dict(r) for r in rows]}


@app.get("/analytics/daily-crisis")
async def analytics_daily_crisis(
    days: int = Query(30, ge=1, le=365),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """Daily counts of crisis_flag events for the user."""
    async with db_session() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT day, crisis_events
                FROM daily_crisis_counts
                WHERE user_id = $1
                  AND day >= (now() - $2::interval)
                ORDER BY day
                """,
                current_user["id"],
                f"{days} days",
            )
        except Exception:
            rows = []
    return {"items": [dict(r) for r in rows]}


@app.get("/analytics/daily-intents")
async def analytics_daily_intents(
    days: int = Query(14, ge=1, le=120),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """Daily distribution of detected intents (from conversation messages)."""
    async with db_session() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT day, intent, intent_messages
                FROM daily_intent_counts
                WHERE user_id = $1
                  AND day >= (now() - $2::interval)
                ORDER BY day, intent
                """,
                current_user["id"],
                f"{days} days",
            )
        except Exception:
            rows = []
    return {"items": [dict(r) for r in rows]}


@app.get("/analytics/conversations/recent")
async def analytics_recent_conversations(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """Recent conversations with basic engagement metrics."""
    async with db_session() as conn:
        rows = await conn.fetch(
            """
            SELECT id,
                   start_at,
                   end_at,
                   message_count,
                   EXTRACT(EPOCH FROM (COALESCE(end_at, now()) - start_at))::int AS duration_seconds,
                   metadata
            FROM user_conversations
            WHERE user_id = $1
            ORDER BY start_at DESC
            LIMIT $2
            """,
            current_user["id"],
            limit,
        )
    return {"items": [dict(r) for r in rows]}

