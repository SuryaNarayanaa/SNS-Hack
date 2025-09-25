"""Authentication utilities leveraging asyncpg storage."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple, cast

import asyncpg

from db import db_session

HASH_NAME = "sha256"
HASH_ITERATIONS = 390_000
DEFAULT_SESSION_TTL = timedelta(hours=12)
GUEST_SESSION_TTL = timedelta(hours=4)


class AuthError(Exception):
    """Base class for authentication-related issues."""


class DuplicateUserError(AuthError):
    """Raised when attempting to create a user that already exists."""


class InvalidCredentialsError(AuthError):
    """Raised when supplied credentials are invalid."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, HASH_ITERATIONS)
    return f"{_b64encode(salt)}:{_b64encode(derived)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, hash_b64 = stored.split(":", 1)
    except ValueError:
        return False
    salt = _b64decode(salt_b64)
    expected = _b64decode(hash_b64)
    derived = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, HASH_ITERATIONS)
    return secrets.compare_digest(derived, expected)


async def create_user(username: str, password: str, *, is_guest: bool = False) -> dict[str, Any]:
    hashed_password: Optional[str] = None if is_guest else hash_password(password)
    try:
        async with db_session() as conn:
            record = await conn.fetchrow(
                """
                INSERT INTO auth_users (username, hashed_password, is_guest)
                VALUES ($1, $2, $3)
                RETURNING id, username, is_guest, created_at
                """,
                username,
                hashed_password,
                is_guest,
            )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateUserError("Username already exists") from exc

    if record is None:  # pragma: no cover - unexpected
        raise RuntimeError("User creation failed")

    return {
        "id": record["id"],
        "username": record["username"],
        "is_guest": record["is_guest"],
        "created_at": record["created_at"],
    }


async def authenticate_user(username: str, password: str) -> dict[str, Any]:
    async with db_session() as conn:
        record = await conn.fetchrow(
            """
            SELECT id, username, hashed_password, is_guest, created_at
            FROM auth_users
            WHERE username = $1
            """,
            username,
        )

    if not record or not record["hashed_password"]:
        raise InvalidCredentialsError("Invalid username or password")

    if not verify_password(password, record["hashed_password"]):
        raise InvalidCredentialsError("Invalid username or password")

    return {key: record[key] for key in ("id", "username", "is_guest", "created_at")}


async def _issue_session(conn: asyncpg.Connection, user_id: int, *, ttl: timedelta) -> Tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + ttl

    while True:
        token = secrets.token_urlsafe(32)
        try:
            await conn.execute(
                """
                INSERT INTO auth_sessions (token, user_id, expires_at)
                VALUES ($1, $2, $3)
                """,
                token,
                user_id,
                expires_at,
            )
            break
        except asyncpg.UniqueViolationError:
            continue

    return token, expires_at


async def create_session(user_id: int, *, ttl: timedelta = DEFAULT_SESSION_TTL) -> Tuple[str, datetime]:
    async with db_session() as conn:
        await conn.execute("DELETE FROM auth_sessions WHERE expires_at <= NOW()")
        return await _issue_session(conn, user_id, ttl=ttl)


async def create_guest_session(display_name: str | None = None) -> Tuple[str, dict[str, Any], datetime]:
    username = display_name or f"guest-{secrets.token_hex(4)}"
    async with db_session() as conn:
        record = await conn.fetchrow(
            """
            INSERT INTO auth_users (username, is_guest)
            VALUES ($1, TRUE)
            RETURNING id, username, is_guest, created_at
            """,
            username,
        )
        if record is None:  # pragma: no cover - unexpected
            raise RuntimeError("Guest user creation failed")

        token, expires_at = await _issue_session(conn, record["id"], ttl=GUEST_SESSION_TTL)
        user = {
        "id": record["id"],
        "username": record["username"],
        "is_guest": record["is_guest"],
        "created_at": record["created_at"],
    }

    return token, user, expires_at


async def get_user_by_token(token: str) -> Optional[dict[str, Any]]:
    async with db_session() as conn:
        record = await conn.fetchrow(
            """
            SELECT u.id, u.username, u.is_guest, u.created_at, s.expires_at
            FROM auth_sessions s
            JOIN auth_users u ON u.id = s.user_id
            WHERE s.token = $1 AND s.expires_at > NOW()
            """,
            token,
        )

    if not record:
        return None

    return {
        "id": record["id"],
        "username": record["username"],
        "is_guest": record["is_guest"],
        "created_at": record["created_at"],
        "expires_at": record["expires_at"],
    }


async def revoke_session(token: str) -> None:
    async with db_session() as conn:
        await conn.execute("DELETE FROM auth_sessions WHERE token = $1", token)


async def cleanup_expired_sessions() -> None:
    async with db_session() as conn:
        await conn.execute("DELETE FROM auth_sessions WHERE expires_at <= NOW()")