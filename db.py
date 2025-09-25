"""Database utilities for asyncpg-backed storage."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Any, Sequence

import asyncpg
from dotenv import load_dotenv
import asyncio

load_dotenv()


CONNECTION = os.getenv("TIMESCALE_SERVICE_URL")


USER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS auth_users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
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
    # --- Mental / Behavioral telemetry schema additions ---
    USER_CONVERSATIONS_SQL = """
    CREATE TABLE IF NOT EXISTS user_conversations (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
        session_token TEXT NULL,
        title TEXT NULL,
        summary TEXT NULL,
        start_at TIMESTAMPTZ DEFAULT NOW(),
        end_at TIMESTAMPTZ NULL,
        message_count INTEGER DEFAULT 0,
        metadata JSONB NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """

    BEHAVIORAL_EVENTS_SQL = """
    CREATE TABLE IF NOT EXISTS behavioral_events (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
        session_token TEXT NULL,
        event_type TEXT NOT NULL,              -- mood_rating | stress_rating | crisis_flag | coping_action | intent_detected | memory_write | handoff
        numeric_value NUMERIC NULL,            -- normalized score 0..1 or scale mapping
        text_value TEXT NULL,                  -- short label / category / freeform
        tags TEXT[] NULL,                      -- classification tags
        metadata JSONB NULL,                   -- structured payload (confidence, agent, risk_level)
        occurred_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """

    CONVERSATION_BEHAVIOR_SQL = """
    CREATE TABLE IF NOT EXISTS conversation_behavior (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
        conversation_id BIGINT REFERENCES user_conversations(id) ON DELETE SET NULL,
        session_token TEXT NULL,
        role TEXT NOT NULL,                    -- user | agent | system
        content TEXT NULL,
        sentiment NUMERIC NULL,
        intent TEXT NULL,
        coping_action TEXT NULL,
        response_latency_ms INTEGER NULL,
        metadata JSONB NULL,
        occurred_at TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """

    async with db_session() as conn:
        # Core auth/session tables
        await conn.execute(USER_TABLE_SQL)
        await conn.execute(SESSION_TABLE_SQL)
        await conn.execute(SESSION_INDEX_SQL)

        # Backfill legacy auth_users table if it was created without newer columns/constraints
        try:
            # Add email column if missing
            await conn.execute(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                      SELECT 1 FROM information_schema.columns
                      WHERE table_name='auth_users' AND column_name='email'
                  ) THEN
                      ALTER TABLE auth_users ADD COLUMN email TEXT;
                  END IF;
                END $$;
                """
            )
            # Ensure NOT NULL & unique constraint if data permits
            await conn.execute(
                """
                DO $$
                BEGIN
                  IF EXISTS (
                      SELECT 1 FROM information_schema.columns
                      WHERE table_name='auth_users' AND column_name='email'
                  ) THEN
                      -- Fill nulls with placeholder values to allow constraint application (optional)
                      UPDATE auth_users SET email = CONCAT('placeholder-', id, '@example.invalid')
                      WHERE email IS NULL;
                      ALTER TABLE auth_users ALTER COLUMN email SET NOT NULL;
                  END IF;
                END $$;
                """
            )
            await conn.execute(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                      SELECT 1 FROM pg_constraint
                      WHERE conrelid = 'auth_users'::regclass
                        AND contype = 'u'
                        AND conname = 'auth_users_email_key'
                  ) THEN
                      ALTER TABLE auth_users ADD CONSTRAINT auth_users_email_key UNIQUE (email);
                  END IF;
                END $$;
                """
            )
        except Exception:
            pass

        # Behavioral tables
        await conn.execute(USER_CONVERSATIONS_SQL)
        await conn.execute(BEHAVIORAL_EVENTS_SQL)
        await conn.execute(CONVERSATION_BEHAVIOR_SQL)

        # Enable timescaledb + hypertables (best effort)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
            await conn.execute(
                "SELECT create_hypertable('behavioral_events','occurred_at', chunk_time_interval => INTERVAL '7 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
            )
            await conn.execute(
                "SELECT create_hypertable('conversation_behavior','occurred_at', chunk_time_interval => INTERVAL '7 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
            )
        except Exception:
            # Extension may not be available / insufficient privs
            pass

        # Indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_behavioral_user_time ON behavioral_events (user_id, occurred_at DESC);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_behavioral_event_type ON behavioral_events (event_type);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_behavioral_metadata_gin ON behavioral_events USING GIN (metadata);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_behavior_user_time ON conversation_behavior (user_id, occurred_at DESC);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_behavior_intent ON conversation_behavior (intent);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_behavior_metadata_gin ON conversation_behavior USING GIN (metadata);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_conversations_user_time ON user_conversations (user_id, start_at DESC);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_conversations_metadata_gin ON user_conversations USING GIN (metadata);")

        # Continuous aggregates & policies (best effort)
        try:
            # Daily average mood / stress (uses numeric_value where event_type LIKE '%_rating')
            await conn.execute(
                """
                CREATE MATERIALIZED VIEW IF NOT EXISTS daily_behavior_scores
                WITH (timescaledb.continuous) AS
                SELECT time_bucket('1 day', occurred_at) AS day,
                       user_id,
                       event_type,
                       avg(numeric_value) AS avg_score,
                       count(*) AS samples
                FROM behavioral_events
                WHERE event_type LIKE '%_rating'
                GROUP BY day, user_id, event_type;
                """
            )
            # Daily crisis counts
            await conn.execute(
                """
                CREATE MATERIALIZED VIEW IF NOT EXISTS daily_crisis_counts
                WITH (timescaledb.continuous) AS
                SELECT time_bucket('1 day', occurred_at) AS day,
                       user_id,
                       count(*) AS crisis_events
                FROM behavioral_events
                WHERE event_type = 'crisis_flag'
                GROUP BY day, user_id;
                """
            )
            # Daily intents distribution
            await conn.execute(
                """
                CREATE MATERIALIZED VIEW IF NOT EXISTS daily_intent_counts
                WITH (timescaledb.continuous) AS
                SELECT time_bucket('1 day', occurred_at) AS day,
                       user_id,
                       intent,
                       count(*) AS intent_messages
                FROM conversation_behavior
                WHERE intent IS NOT NULL
                GROUP BY day, user_id, intent;
                """
            )
        except Exception:
            pass

        # Compression & retention policies (best effort)
        try:
            await conn.execute("ALTER TABLE behavioral_events SET (timescaledb.compress, timescaledb.compress_segmentby='user_id');")
            await conn.execute("ALTER TABLE conversation_behavior SET (timescaledb.compress, timescaledb.compress_segmentby='user_id');")
            await conn.execute("SELECT add_compression_policy('behavioral_events', INTERVAL '14 days');")
            await conn.execute("SELECT add_compression_policy('conversation_behavior', INTERVAL '14 days');")
            await conn.execute("SELECT add_drop_chunks_policy('behavioral_events', INTERVAL '365 days');")
            await conn.execute("SELECT add_drop_chunks_policy('conversation_behavior', INTERVAL '365 days');")
        except Exception:
            pass

        # Refresh policies for continuous aggregates (if available)
        try:
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_behavior_scores', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');")
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_crisis_counts', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');")
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_intent_counts', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '2 hours');")
        except Exception:
            pass


# ---------------- Ingestion Helpers -----------------

async def _safe_exec(query: str, *params: Any) -> None:
    try:
        async with db_session() as conn:
            await conn.execute(query, *params)
    except Exception:
        # Swallow errors to avoid breaking user chat flow; consider logging.
        pass


async def insert_behavioral_event(
    user_id: int | None,
    event_type: str,
    *,
    numeric_value: float | None = None,
    text_value: str | None = None,
    tags: Sequence[str] | None = None,
    metadata: dict | None = None,
    session_token: str | None = None,
    occurred_at: str | None = None,
) -> None:
    if not user_id:
        return
    await _safe_exec(
        """
        INSERT INTO behavioral_events (user_id, session_token, event_type, numeric_value, text_value, tags, metadata, occurred_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7, COALESCE($8, now()))
        """,
        user_id,
        session_token,
        event_type,
        numeric_value,
        text_value,
        list(tags) if tags else None,
        metadata,
        occurred_at,
    )


async def insert_conversation_message(
    user_id: int | None,
    *,
    role: str,
    content: str | None,
    intent: str | None = None,
    sentiment: float | None = None,
    coping_action: str | None = None,
    response_latency_ms: int | None = None,
    metadata: dict | None = None,
    session_token: str | None = None,
    conversation_id: int | None = None,
) -> None:
    if not user_id:
        return
    await _safe_exec(
        """
        INSERT INTO conversation_behavior (user_id, conversation_id, session_token, role, content, sentiment, intent, coping_action, response_latency_ms, metadata)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
        user_id,
        conversation_id,
        session_token,
        role,
        content,
        sentiment,
        intent,
        coping_action,
        response_latency_ms,
        metadata,
    )


async def create_conversation(
    user_id: int | None,
    *,
    session_token: str | None = None,
    title: str | None = None,
    metadata: dict | None = None,
) -> int | None:
    if not user_id:
        return None
    try:
        async with db_session() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_conversations (user_id, session_token, title, metadata)
                VALUES ($1,$2,$3,$4) RETURNING id
                """,
                user_id,
                session_token,
                title,
                metadata,
            )
            return int(row["id"]) if row else None
    except Exception:
        return None


async def update_conversation_stats(
    conversation_id: int | None,
    *,
    end: bool = False,
    increment_messages: int = 0,
    summary: str | None = None,
    metadata: dict | None = None,
) -> None:
    if not conversation_id:
        return
    sets: list[str] = []
    params: list[Any] = []
    if end:
        sets.append("end_at = COALESCE(end_at, now())")
    if increment_messages:
        sets.append(f"message_count = message_count + ${len(params)+2}")
        params.append(increment_messages)
    if summary is not None:
        sets.append(f"summary = ${len(params)+2}")
        params.append(summary)
    if metadata is not None:
        sets.append(f"metadata = COALESCE(${len(params)+2}, metadata)")
        params.append(metadata)
    sets.append("updated_at = now()")
    if not sets:
        return
    query = f"UPDATE user_conversations SET {', '.join(sets)} WHERE id = $1"
    try:
        async with db_session() as conn:
            await conn.execute(query, conversation_id, *params)
    except Exception:
        pass


async def drop_all_tables(confirm: bool = False, drop_users: bool = False) -> None:
    """Dangerous: drop all behavioral + auth tables & continuous aggregates.

    Parameters:
        confirm: must be True to proceed.
        drop_users: if True also drops auth_users (and cascades sessions).
    """
    if not confirm:
        raise ValueError("Set confirm=True to execute destructive drop_all_tables.")
    statements = [
        "DROP MATERIALIZED VIEW IF EXISTS daily_intent_counts;",
        "DROP MATERIALIZED VIEW IF EXISTS daily_crisis_counts;",
        "DROP MATERIALIZED VIEW IF EXISTS daily_behavior_scores;",
        "DROP TABLE IF EXISTS conversation_behavior CASCADE;",
        "DROP TABLE IF EXISTS behavioral_events CASCADE;",
        "DROP TABLE IF EXISTS user_conversations CASCADE;",
        "DROP TABLE IF EXISTS auth_sessions CASCADE;",
    ]
    if drop_users:
        statements.append("DROP TABLE IF EXISTS auth_users CASCADE;")
    async with db_session() as conn:
        for stmt in statements:
            try:
                await conn.execute(stmt)
            except Exception:
                pass


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


# if __name__ == "__main__":
#     asyncio.run(drop_all_tables(confirm=True, drop_users=True))