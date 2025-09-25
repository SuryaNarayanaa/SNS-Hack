"""Database utilities for asyncpg-backed storage."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
from dotenv import load_dotenv

load_dotenv()


CONNECTION = os.getenv("TIMESCALE_SERVICE_URL")


USER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auth_users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    hashed_password TEXT,
    is_guest BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


SESSION_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at
    ON auth_sessions (expires_at);
"""


def _require_connection_string() -> str:
    if not CONNECTION:
        raise RuntimeError("TIMESCALE_SERVICE_URL environment variable must be set")
    return CONNECTION


async def get_db() -> asyncpg.Connection:
    """Create a one-off connection; caller is responsible for closing it."""

    dsn = _require_connection_string()
    return await asyncpg.connect(dsn)


@asynccontextmanager
async def db_session() -> AsyncIterator[asyncpg.Connection]:
    """Context manager that opens and closes a connection automatically."""

    conn = await get_db()
    try:
        yield conn
    finally:
        await conn.close()


async def init_db() -> None:
    """Ensure required tables and indexes exist."""

    async with db_session() as conn:
        await conn.execute(USER_TABLE_SQL)
        await conn.execute(SESSION_TABLE_SQL)
        await conn.execute(SESSION_INDEX_SQL)


async def test_db_connection() -> None:
    """Diagnostic helper to verify database connectivity and extensions."""

    try:
        async with db_session() as conn:
            print("Database connection successful.")
            extensions = await conn.fetch("SELECT extname, extversion FROM pg_extension")
            for extension in extensions:
                print(extension)
            print("Connection closed.")
    except Exception as exc:  # pragma: no cover - diagnostic utility
        print(f"Connection failed: {exc}")
