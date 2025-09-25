"""Database utilities for asyncpg-backed storage."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator, Any, Iterable, Mapping, Sequence

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


MINDFULNESS_GOALS_SQL = """
CREATE TABLE IF NOT EXISTS mindfulness_goals (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    short_tagline TEXT NULL,
    description TEXT NULL,
    default_exercise_type TEXT NOT NULL,
    recommended_durations INTEGER[] NULL,
    recommended_soundscape_slugs TEXT[] NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


MINDFULNESS_SOUNDSCAPES_SQL = """
CREATE TABLE IF NOT EXISTS mindfulness_soundscapes (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NULL,
    audio_url TEXT NOT NULL,
    loop_seconds INTEGER NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


MINDFULNESS_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS mindfulness_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    exercise_type TEXT NOT NULL,
    goal_code TEXT NULL REFERENCES mindfulness_goals(code) ON DELETE SET NULL,
    soundscape_id BIGINT NULL REFERENCES mindfulness_soundscapes(id) ON DELETE SET NULL,
    planned_duration_seconds INTEGER NOT NULL,
    start_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_at TIMESTAMPTZ NULL,
    actual_duration_seconds INTEGER NULL,
    cycles_completed INTEGER NULL,
    rating_relaxation SMALLINT NULL,
    rating_stress_before SMALLINT NULL,
    rating_stress_after SMALLINT NULL,
    rating_mood_before SMALLINT NULL,
    rating_mood_after SMALLINT NULL,
    score_restful NUMERIC(5,2) NULL,
    score_focus NUMERIC(5,2) NULL,
    tags TEXT[] NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


MINDFULNESS_SESSIONS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mindfulness_sessions_user_time
    ON mindfulness_sessions (user_id, start_at DESC);
"""


MINDFULNESS_SESSIONS_TYPE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mindfulness_sessions_exercise
    ON mindfulness_sessions (exercise_type);
"""


MINDFULNESS_SESSION_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS mindfulness_session_events (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES mindfulness_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    numeric_value NUMERIC NULL,
    text_value TEXT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


MINDFULNESS_SESSION_EVENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mindfulness_session_events_session_time
    ON mindfulness_session_events (session_id, occurred_at);
"""


MINDFUL_DAILY_MINUTES_VIEW_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mindful_daily_minutes
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', COALESCE(end_at, start_at)) AS day,
       user_id,
       exercise_type,
       SUM(actual_duration_seconds)::numeric / 60.0 AS minutes,
       COUNT(*) AS sessions
FROM mindfulness_sessions
WHERE end_at IS NOT NULL
  AND actual_duration_seconds IS NOT NULL
  AND actual_duration_seconds >= 60
GROUP BY day, user_id, exercise_type;
"""


MINDFULNESS_MIN_DURATION_SECONDS = 60


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

        # Mindfulness catalog + session tables
        await conn.execute(MINDFULNESS_GOALS_SQL)
        await conn.execute(MINDFULNESS_SOUNDSCAPES_SQL)
        await conn.execute(MINDFULNESS_SESSIONS_SQL)
        await conn.execute(MINDFULNESS_SESSIONS_INDEX_SQL)
        await conn.execute(MINDFULNESS_SESSIONS_TYPE_INDEX_SQL)
        await conn.execute(MINDFULNESS_SESSION_EVENTS_SQL)
        await conn.execute(MINDFULNESS_SESSION_EVENTS_INDEX_SQL)

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
            await conn.execute(
                "SELECT create_hypertable('mindfulness_sessions','start_at', chunk_time_interval => INTERVAL '7 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
            )
            await conn.execute(
                "SELECT create_hypertable('mindfulness_session_events','occurred_at', chunk_time_interval => INTERVAL '7 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
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
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mindfulness_sessions_end_at ON mindfulness_sessions (end_at);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mindfulness_sessions_goal ON mindfulness_sessions (goal_code);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mindfulness_soundscapes_active ON mindfulness_soundscapes (is_active);")

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
            await conn.execute(MINDFUL_DAILY_MINUTES_VIEW_SQL)
        except Exception:
            try:
                await conn.execute(
                    """
                    CREATE MATERIALIZED VIEW IF NOT EXISTS mindful_daily_minutes AS
                    SELECT date_trunc('day', COALESCE(end_at, start_at)) AS day,
                           user_id,
                           exercise_type,
                           SUM(actual_duration_seconds)::numeric / 60.0 AS minutes,
                           COUNT(*) AS sessions
                    FROM mindfulness_sessions
                    WHERE end_at IS NOT NULL
                      AND actual_duration_seconds IS NOT NULL
                      AND actual_duration_seconds >= 60
                    GROUP BY day, user_id, exercise_type;
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
            await conn.execute("ALTER TABLE mindfulness_sessions SET (timescaledb.compress, timescaledb.compress_segmentby='user_id');")
            await conn.execute("ALTER TABLE mindfulness_session_events SET (timescaledb.compress, timescaledb.compress_segmentby='user_id');")
            await conn.execute("SELECT add_compression_policy('mindfulness_sessions', INTERVAL '30 days');")
            await conn.execute("SELECT add_compression_policy('mindfulness_session_events', INTERVAL '30 days');")
        except Exception:
            pass

        # Refresh policies for continuous aggregates (if available)
        try:
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_behavior_scores', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');")
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_crisis_counts', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');")
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_intent_counts', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '2 hours');")
            await conn.execute("SELECT add_continuous_aggregate_policy('mindful_daily_minutes', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '2 hours');")
        except Exception:
            pass

        # Seed baseline mindfulness catalog entries (best effort)
        try:
            await conn.execute(
                """
                INSERT INTO mindfulness_goals (code, title, short_tagline, description, default_exercise_type, recommended_durations, recommended_soundscape_slugs)
                VALUES
                ('sleep_better','I want to sleep better','Improve nightly rest','Support better sleep hygiene','sleep','{10,20,30}','{rainforest,zen-garden}'),
                ('reduce_stress','I want to reduce stress','Calm the mind','Lower acute stress through breathing','breathing','{5,10,15,25}','{zen-garden,mountain-stream}'),
                ('focus_better','I want to focus better','Sharpen concentration','Improve focus via guided breathing','breathing','{10,20,30}','{zen-garden}'),
                ('calm_evening','Wind down the evening','Slow your thoughts before bed','sleep','{5,15,25}','{mountain-stream}')
                ON CONFLICT (code) DO NOTHING;
                """
            )
            await conn.execute(
                """
                INSERT INTO mindfulness_soundscapes (slug, name, description, audio_url, loop_seconds)
                VALUES
                ('zen-garden','Zen Garden','Soft chimes and water','https://cdn/app/audio/zen-garden.mp3',90),
                ('mountain-stream','Mountain Stream','Flowing water ambience','https://cdn/app/audio/mountain-stream.mp3',120),
                ('rainforest','Rainforest Dawn','Gentle rain with distant wildlife','https://cdn/app/audio/rainforest.mp3',150)
                ON CONFLICT (slug) DO NOTHING;
                """
            )
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


# ---------------- Mindfulness Helpers -----------------

def _clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, float(value)))


def _range_to_interval(range_key: str | None) -> str | None:
    if not range_key:
        return None
    key = range_key.lower().strip()
    mapping = {
        "7d": "7 days",
        "30d": "30 days",
        "90d": "90 days",
        "180d": "180 days",
        "365d": "365 days",
        "1y": "1 year",
    }
    if key in mapping:
        return mapping[key]
    if key.endswith("d") and key[:-1].isdigit():
        return f"{int(key[:-1])} days"
    if key.endswith("w") and key[:-1].isdigit():
        weeks = int(key[:-1])
        return f"{weeks * 7} days"
    return None


async def list_mindfulness_goals(exercise_type: str | None = None) -> list[dict[str, Any]]:
    query = (
        "SELECT code, title, short_tagline, description, default_exercise_type, "
        "recommended_durations, recommended_soundscape_slugs, metadata, created_at "
        "FROM mindfulness_goals"
    )
    params: list[Any] = []
    if exercise_type:
        params.append(exercise_type)
        query += " WHERE default_exercise_type = $1"
    query += " ORDER BY title"
    async with db_session() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


async def list_mindfulness_soundscapes(active: bool | None = True) -> list[dict[str, Any]]:
    base_query = (
        "SELECT id, slug, name, description, audio_url, loop_seconds, is_active, created_at "
        "FROM mindfulness_soundscapes"
    )
    params: list[Any] = []
    if active is None:
        query = base_query + " ORDER BY name"
        async with db_session() as conn:
            rows = await conn.fetch(query)
    else:
        params.append(active)
        query = base_query + " WHERE is_active = $1 ORDER BY name"
        async with db_session() as conn:
            rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


async def create_mindfulness_session(
    user_id: int,
    *,
    exercise_type: str,
    planned_duration_minutes: int,
    goal_code: str | None = None,
    soundscape_id: int | None = None,
    metadata: dict | None = None,
    tags: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    planned_seconds = max(int(planned_duration_minutes) * 60, 1)
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mindfulness_sessions (
                user_id, exercise_type, goal_code, soundscape_id, planned_duration_seconds, tags, metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
            """,
            user_id,
            exercise_type,
            goal_code,
            soundscape_id,
            planned_seconds,
            list(tags) if tags else None,
            metadata,
        )
    return dict(row) if row else None


async def get_mindfulness_session(session_id: int, user_id: int) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM mindfulness_sessions WHERE id = $1 AND user_id = $2",
            session_id,
            user_id,
        )
    return dict(row) if row else None


async def query_mindfulness_sessions(
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
    exercise_type: str | None = None,
    goal_code: str | None = None,
    date_range: str | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    conditions = ["user_id = $1"]
    params: list[Any] = [user_id]

    if exercise_type:
        params.append(exercise_type)
        conditions.append(f"exercise_type = ${len(params)}")
    if goal_code:
        params.append(goal_code)
        conditions.append(f"goal_code = ${len(params)}")
    interval = _range_to_interval(date_range)
    if interval:
        params.append(interval)
        conditions.append(f"start_at >= now() - ${len(params)}::interval")

    where_clause = " AND ".join(conditions)
    params.append(limit)
    limit_index = len(params)
    params.append(offset)
    offset_index = len(params)

    query = (
        f"SELECT * FROM mindfulness_sessions WHERE {where_clause} "
        f"ORDER BY start_at DESC LIMIT ${limit_index} OFFSET ${offset_index}"
    )

    async with db_session() as conn:
        rows = await conn.fetch(query, *params)

    next_offset = offset + len(rows) if len(rows) == limit else None
    return [dict(row) for row in rows], next_offset


async def update_mindfulness_session_progress(
    session_id: int,
    user_id: int,
    *,
    cycles_completed: int | None = None,
    elapsed_seconds: int | None = None,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = [session_id, user_id]

    if cycles_completed is not None:
        params.append(cycles_completed)
        sets.append(f"cycles_completed = ${len(params)}")
    if elapsed_seconds is not None:
        params.append(max(int(elapsed_seconds), 0))
        sets.append(f"actual_duration_seconds = ${len(params)}")
    if metadata is not None:
        params.append(metadata)
        sets.append(f"metadata = COALESCE(metadata, '{{}}'::jsonb) || ${len(params)}::jsonb")

    if not sets:
        return await get_mindfulness_session(session_id, user_id)

    query = (
        "UPDATE mindfulness_sessions "
        f"SET {', '.join(sets)} "
        "WHERE id = $1 AND user_id = $2 AND end_at IS NULL RETURNING *"
    )

    async with db_session() as conn:
        row = await conn.fetchrow(query, *params)

    if row is None:
        return await get_mindfulness_session(session_id, user_id)
    return dict(row)


def _compute_restful_score(ratings: Mapping[str, Any]) -> float | None:
    rating_relaxation = ratings.get("rating_relaxation")
    stress_before = ratings.get("rating_stress_before")
    stress_after = ratings.get("rating_stress_after")
    if rating_relaxation is None and stress_before is None and stress_after is None:
        return None
    delta_stress = 0
    if stress_before is not None and stress_after is not None:
        delta_stress = stress_before - stress_after
    base = 50 + (delta_stress * 5)
    if rating_relaxation is not None:
        base += rating_relaxation * 3
    return _clamp_score(base)


def _compute_focus_score(
    goal_code: str | None,
    ratings: Mapping[str, Any],
    actual_seconds: int,
    planned_seconds: int,
) -> float | None:
    if not goal_code or not goal_code.startswith("focus"):
        return None
    ratio = 0.0
    if planned_seconds > 0:
        ratio = min(actual_seconds / planned_seconds, 2.0)
    mood_before = ratings.get("rating_mood_before")
    mood_after = ratings.get("rating_mood_after")
    mood_delta = 0
    if mood_before is not None and mood_after is not None:
        mood_delta = mood_after - mood_before
    base = 40 + (ratio * 30) + (mood_delta * 5)
    return _clamp_score(base)


async def complete_mindfulness_session(
    session_id: int,
    user_id: int,
    *,
    cycles_completed: int | None = None,
    rating_relaxation: int | None = None,
    rating_stress_before: int | None = None,
    rating_stress_after: int | None = None,
    rating_mood_before: int | None = None,
    rating_mood_after: int | None = None,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    async with db_session() as conn:
        current_row = await conn.fetchrow(
            "SELECT * FROM mindfulness_sessions WHERE id = $1 AND user_id = $2",
            session_id,
            user_id,
        )

        if current_row is None:
            return None

        current = dict(current_row)

        start_at: datetime = current_row["start_at"]
        existing_end: datetime | None = current_row["end_at"]
        effective_end = existing_end or datetime.now(timezone.utc)
        actual_seconds = max(int((effective_end - start_at).total_seconds()), 0)
        if actual_seconds == 0:
            actual_seconds = current.get("planned_duration_seconds") or 0

        ratings: dict[str, Any] = {
            "rating_relaxation": rating_relaxation if rating_relaxation is not None else current.get("rating_relaxation"),
            "rating_stress_before": rating_stress_before if rating_stress_before is not None else current.get("rating_stress_before"),
            "rating_stress_after": rating_stress_after if rating_stress_after is not None else current.get("rating_stress_after"),
            "rating_mood_before": rating_mood_before if rating_mood_before is not None else current.get("rating_mood_before"),
            "rating_mood_after": rating_mood_after if rating_mood_after is not None else current.get("rating_mood_after"),
        }

        rating_updates_present = any(
            value is not None
            for value in (
                rating_relaxation,
                rating_stress_before,
                rating_stress_after,
                rating_mood_before,
                rating_mood_after,
            )
        )

        should_compute_scores = (
            current.get("score_restful") is None
            or current.get("score_focus") is None
            or rating_updates_present
            or existing_end is None
        )
        restful_score = current.get("score_restful")
        focus_score = current.get("score_focus")

        if should_compute_scores:
            maybe_restful = _compute_restful_score(ratings)
            maybe_focus = _compute_focus_score(
                current.get("goal_code"),
                ratings,
                actual_seconds,
                current.get("planned_duration_seconds") or 0,
            )
            if maybe_restful is not None:
                restful_score = round(maybe_restful, 2)
            if maybe_focus is not None:
                focus_score = round(maybe_focus, 2)
            elif rating_updates_present and (current.get("goal_code") or "").startswith("focus"):
                focus_score = None

        sets: list[str] = []
        params: list[Any] = [session_id, user_id]

        if existing_end is None:
            sets.append("end_at = now()")
        if current.get("actual_duration_seconds") is None or existing_end is None:
            params.append(actual_seconds)
            sets.append(f"actual_duration_seconds = ${len(params)}")
        if cycles_completed is not None:
            params.append(cycles_completed)
            sets.append(f"cycles_completed = ${len(params)}")

        for column, value in (
            ("rating_relaxation", ratings["rating_relaxation"]),
            ("rating_stress_before", ratings["rating_stress_before"]),
            ("rating_stress_after", ratings["rating_stress_after"]),
            ("rating_mood_before", ratings["rating_mood_before"]),
            ("rating_mood_after", ratings["rating_mood_after"]),
        ):
            if value is not None:
                params.append(value)
                sets.append(f"{column} = ${len(params)}")

        if should_compute_scores:
            if restful_score is not None:
                params.append(restful_score)
                sets.append(f"score_restful = ${len(params)}")
            else:
                sets.append("score_restful = NULL")
            if focus_score is not None:
                params.append(focus_score)
                sets.append(f"score_focus = ${len(params)}")
            elif (current.get("goal_code") or "").startswith("focus"):
                sets.append("score_focus = NULL")

        if metadata is not None:
            params.append(metadata)
            sets.append(f"metadata = COALESCE(metadata, '{{}}'::jsonb) || ${len(params)}::jsonb")

        if not sets:
            return dict(current)

        query = (
            "UPDATE mindfulness_sessions "
            f"SET {', '.join(sets)} "
            "WHERE id = $1 AND user_id = $2 RETURNING *"
        )

        updated = await conn.fetchrow(query, *params)

    return dict(updated) if updated else dict(current)


async def append_mindfulness_session_event(
    session_id: int,
    user_id: int,
    event_type: str,
    *,
    numeric_value: float | None = None,
    text_value: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mindfulness_session_events (
                session_id, user_id, event_type, numeric_value, text_value, occurred_at, metadata
            ) VALUES ($1,$2,$3,$4,$5, COALESCE($6, now()), $7)
            RETURNING *
            """,
            session_id,
            user_id,
            event_type,
            numeric_value,
            text_value,
            occurred_at,
            metadata,
        )
    return dict(row) if row else None


async def list_mindfulness_session_events(
    session_id: int,
    user_id: int,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    async with db_session() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, numeric_value, text_value, occurred_at, metadata, created_at
            FROM mindfulness_session_events
            WHERE session_id = $1 AND user_id = $2
            ORDER BY occurred_at ASC
            LIMIT $3
            """,
            session_id,
            user_id,
            limit,
        )
    return [dict(row) for row in rows]


async def get_active_mindfulness_session(user_id: int) -> dict[str, Any] | None:
    async with db_session() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM mindfulness_sessions
            WHERE user_id = $1 AND end_at IS NULL
            ORDER BY start_at DESC
            LIMIT 1
            """,
            user_id,
        )
    return dict(row) if row else None


async def get_mindful_stats_overview(user_id: int, range_key: str | None = None) -> dict[str, Any]:
    interval = _range_to_interval(range_key) or "30 days"
    async with db_session() as conn:
        aggregate = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(actual_duration_seconds)::numeric / 60.0, 0)::float AS total_minutes,
                COALESCE(SUM(actual_duration_seconds)::numeric / 3600.0, 0)::float AS total_hours,
                COUNT(*) FILTER (
                    WHERE actual_duration_seconds IS NOT NULL AND actual_duration_seconds >= $2 AND end_at IS NOT NULL
                ) AS sessions_count,
                COALESCE(AVG(actual_duration_seconds)::numeric / 60.0, 0)::float AS avg_session_minutes
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND end_at IS NOT NULL
              AND start_at >= now() - $3::interval
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
            interval,
        )

        by_type_rows = await conn.fetch(
            """
            SELECT exercise_type,
                   COALESCE(SUM(actual_duration_seconds)::numeric / 60.0, 0)::float AS minutes,
                   COUNT(*) AS sessions
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND end_at IS NOT NULL
              AND start_at >= now() - $3::interval
            GROUP BY exercise_type
            ORDER BY minutes DESC
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
            interval,
        )

        last_session = await conn.fetchrow(
            """
            SELECT *
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND end_at IS NOT NULL
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND start_at >= now() - $3::interval
            ORDER BY end_at DESC
            LIMIT 1
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
            interval,
        )

        streak_rows = await conn.fetch(
            """
            SELECT DISTINCT (end_at AT TIME ZONE 'UTC')::date AS session_date
            FROM mindfulness_sessions
            WHERE user_id = $1
              AND end_at IS NOT NULL
              AND actual_duration_seconds IS NOT NULL
              AND actual_duration_seconds >= $2
              AND end_at >= (CURRENT_DATE - INTERVAL '400 days')
            ORDER BY session_date DESC
            """,
            user_id,
            MINDFULNESS_MIN_DURATION_SECONDS,
        )

    total_minutes = float(aggregate["total_minutes"]) if aggregate else 0.0
    total_hours = float(aggregate["total_hours"]) if aggregate else 0.0
    sessions_count = int(aggregate["sessions_count"]) if aggregate else 0
    avg_session_minutes = float(aggregate["avg_session_minutes"]) if aggregate else 0.0

    by_exercise_type = [
        {
            "exercise_type": row["exercise_type"],
            "minutes": float(row["minutes"]),
            "sessions": int(row["sessions"]),
        }
        for row in by_type_rows
    ]

    last_session_payload: dict[str, Any] | None = None
    if last_session:
        last_session_dict = dict(last_session)
        actual = last_session_dict.get("actual_duration_seconds") or 0
        last_session_payload = {
            "id": last_session_dict.get("id"),
            "exercise_type": last_session_dict.get("exercise_type"),
            "end_at": last_session_dict.get("end_at"),
            "minutes": round(actual / 60.0, 2) if actual else 0.0,
            "score_restful": float(last_session_dict["score_restful"]) if last_session_dict.get("score_restful") is not None else None,
            "score_focus": float(last_session_dict["score_focus"]) if last_session_dict.get("score_focus") is not None else None,
        }

    streak_dates = {row["session_date"] for row in streak_rows if row["session_date"] is not None}
    today = datetime.now(timezone.utc).date()
    streak = 0
    cursor = today
    while cursor in streak_dates:
        streak += 1
        cursor = cursor - timedelta(days=1)

    return {
        "range": range_key or "30d",
        "total_minutes": round(total_minutes, 2),
        "total_hours": round(total_hours, 2),
        "by_exercise_type": by_exercise_type,
        "streak_days": streak,
        "sessions_count": sessions_count,
        "avg_session_minutes": round(avg_session_minutes, 2) if sessions_count else 0.0,
        "last_session": last_session_payload,
    }


async def get_mindful_daily_minutes(
    user_id: int,
    *,
    days: int = 30,
    exercise_type: str | None = None,
) -> list[dict[str, Any]]:
    interval = f"{max(days, 1)} days"
    async with db_session() as conn:
        try:
            params: list[Any] = [user_id, interval]
            query = (
                "SELECT day::date AS day, exercise_type, minutes "
                "FROM mindful_daily_minutes "
                "WHERE user_id = $1 AND day >= date_trunc('day', now() - $2::interval)"
            )
            if exercise_type:
                params.append(exercise_type)
                query += f" AND exercise_type = ${len(params)}"
            query += " ORDER BY day"
            rows = await conn.fetch(query, *params)
        except Exception:
            params = [user_id, MINDFULNESS_MIN_DURATION_SECONDS, interval]
            query = (
                "SELECT date_trunc('day', COALESCE(end_at, start_at))::date AS day, exercise_type, "
                "COALESCE(SUM(actual_duration_seconds)::numeric / 60.0, 0)::float AS minutes "
                "FROM mindfulness_sessions "
                "WHERE user_id = $1 "
                "AND actual_duration_seconds IS NOT NULL "
                "AND actual_duration_seconds >= $2 "
                "AND COALESCE(end_at, start_at) >= now() - $3::interval"
            )
            if exercise_type:
                params.append(exercise_type)
                query += f" AND exercise_type = ${len(params)}"
            query += " GROUP BY day, exercise_type ORDER BY day"
            rows = await conn.fetch(query, *params)

    items: list[dict[str, Any]] = []
    for row in rows:
        day_value = row["day"]
        if isinstance(day_value, datetime):
            day_iso = day_value.date().isoformat()
        elif isinstance(day_value, date):
            day_iso = day_value.isoformat()
        else:
            day_iso = str(day_value)
        minutes_value = float(row["minutes"]) if row["minutes"] is not None else 0.0
        items.append(
            {
                "day": day_iso,
                "minutes": round(minutes_value, 2),
                "exercise_type": row["exercise_type"],
            }
        )
    return items


# Import mindful routes so FastAPI auto-registration executes when db is imported.
try:  # pragma: no cover - side effect import
    import routes.mindful_routes  # noqa: F401
except Exception:
    pass
# if __name__ == "__main__":
#     asyncio.run(drop_all_tables(confirm=True, drop_users=True))