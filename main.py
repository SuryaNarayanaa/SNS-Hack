"""FastAPI entry point for the SNS Hack backend."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
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
from db import init_db

app = FastAPI(title="Neptune - Mental Healthcare App", version="0.2.0")
bearer_scheme = HTTPBearer(auto_error=False)


class UserResponse(BaseModel):
    id: int
    username: str
    is_guest: bool
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class GuestRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=32)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    user_context: str | None = None


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
        user = await create_user(payload.username, payload.password)
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    token, expires_at = await create_session(user["id"])
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserResponse(**user))


@app.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    try:
        user = await authenticate_user(payload.username, payload.password)
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
        "extra_state": {"auth_user": {key: current_user[key] for key in ("id", "username", "is_guest")}},
    }

    async def generate_response():
        async for event in supervisor.astream_events(initial_state, version="v2"):
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


def main() -> None:
    """Run a development server when executed as a module."""

    port = int(os.getenv("PORT", "8000"))

    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=os.getenv("UVICORN_RELOAD", "true").lower() == "true")


if __name__ == "__main__":
    main()
