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

SLEEP_SCHEDULE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sleep_schedule (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    bedtime_local TIME NOT NULL,
    wake_time_local TIME NOT NULL,
    timezone TEXT NOT NULL,
    active_days SMALLINT[] NOT NULL,
    target_duration_minutes INTEGER,
    auto_set_alarm BOOLEAN DEFAULT FALSE,
    show_stats_auto BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


SLEEP_SCHEDULE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_schedule_user_active
    ON sleep_schedule (user_id, is_active DESC);
"""


SLEEP_SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sleep_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    schedule_id BIGINT REFERENCES sleep_schedule(id) ON DELETE SET NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ,
    in_bed_start_at TIMESTAMPTZ,
    in_bed_end_at TIMESTAMPTZ,
    total_duration_minutes NUMERIC(6,2),
    time_in_bed_minutes NUMERIC(6,2),
    sleep_efficiency NUMERIC(5,2),
    latency_minutes NUMERIC(5,2),
    awakenings_count INTEGER,
    rem_minutes NUMERIC(6,2),
    deep_minutes NUMERIC(6,2),
    light_minutes NUMERIC(6,2),
    awake_minutes NUMERIC(6,2),
    heart_rate_avg NUMERIC(5,2),
    heart_rate_min SMALLINT,
    heart_rate_max SMALLINT,
    score_overall NUMERIC(5,2),
    quality_label TEXT,
    irregularity_flag BOOLEAN,
    device_source TEXT,
    is_auto BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


SLEEP_SESSIONS_START_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_sessions_user_start
    ON sleep_sessions (user_id, start_at DESC);
"""


SLEEP_SESSIONS_END_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_sessions_user_end
    ON sleep_sessions (user_id, end_at DESC);
"""


SLEEP_SESSIONS_ACTIVE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_sessions_active
    ON sleep_sessions (user_id)
    WHERE end_at IS NULL;
"""


SLEEP_STAGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sleep_stages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES sleep_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    duration_seconds INTEGER,
    movement_index NUMERIC,
    heart_rate_avg NUMERIC(5,2),
    metadata JSONB
);
"""


SLEEP_STAGES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_stages_session_start
    ON sleep_stages (session_id, start_at);
"""


SLEEP_INSIGHTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sleep_insights (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    session_id BIGINT REFERENCES sleep_sessions(id) ON DELETE SET NULL,
    insight_type TEXT NOT NULL,
    severity TEXT,
    title TEXT,
    description TEXT,
    suggested_action TEXT,
    status TEXT DEFAULT 'new',
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


SLEEP_INSIGHTS_USER_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_insights_user_created
    ON sleep_insights (user_id, created_at DESC);
"""


SLEEP_INSIGHTS_TYPE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_insights_type
    ON sleep_insights (insight_type);
"""


SLEEP_INSIGHTS_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_insights_status
    ON sleep_insights (status);
"""


SLEEP_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sleep_events (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES sleep_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    numeric_value NUMERIC,
    text_value TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB
);
"""


SLEEP_EVENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sleep_events_session_time
    ON sleep_events (session_id, occurred_at);
"""


SLEEP_DAILY_SUMMARY_VIEW_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS sleep_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', start_at) AS day,
    user_id,
    AVG(score_overall) AS avg_score,
    SUM(total_duration_minutes) AS total_minutes,
    SUM(rem_minutes) AS rem_minutes,
    SUM(deep_minutes) AS deep_minutes,
    SUM(light_minutes) AS light_minutes,
    SUM(awakenings_count) AS awakenings,
    AVG(sleep_efficiency) AS efficiency_avg
FROM sleep_sessions
WHERE end_at IS NOT NULL
GROUP BY day, user_id;
"""


MOOD_ENTRIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mood_entries (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    mood_value SMALLINT NOT NULL,
    mood_label TEXT NOT NULL,
    note TEXT NULL,
    improvement_flag BOOLEAN NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


MOOD_ENTRIES_USER_CREATED_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mood_entries_user_created
    ON mood_entries (user_id, created_at DESC);
"""


MOOD_ENTRIES_VALUE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mood_entries_user_value
    ON mood_entries (user_id, mood_value);
"""


MOOD_ENTRIES_IMPROVEMENT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mood_entries_improvement
    ON mood_entries (user_id)
    WHERE improvement_flag IS TRUE;
"""


MOOD_SUGGESTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mood_suggestions (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    suggestion_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NULL,
    tags TEXT[] NULL,
    priority SMALLINT NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'new',
    resolved_at TIMESTAMPTZ NULL,
    metadata JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


MOOD_SUGGESTIONS_USER_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mood_suggestions_user_status
    ON mood_suggestions (user_id, status);
"""


MOOD_SUGGESTIONS_CREATED_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mood_suggestions_user_created
    ON mood_suggestions (user_id, created_at DESC);
"""


MOOD_SUGGESTIONS_STATUS_PRIORITY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_mood_suggestions_status_priority
    ON mood_suggestions (status, priority DESC);
"""


MOOD_DAILY_STATS_VIEW_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mood_daily_stats
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', created_at) AS day,
       user_id,
       AVG(mood_value)::float AS avg_mood_value,
       COUNT(*) AS entries_count,
       MIN(mood_value) AS min_mood_value,
       MAX(mood_value) AS max_mood_value,
       MAX(mood_value) - MIN(mood_value) AS mood_swing,
       (ARRAY_AGG(mood_value ORDER BY created_at ASC))[1] AS first_mood_value,
       (ARRAY_AGG(mood_value ORDER BY created_at DESC))[1] AS last_mood_value,
       COUNT(*) FILTER (WHERE mood_value >= 3) AS positive_entries,
       COUNT(*) FILTER (WHERE mood_value <= 2) AS negative_entries
FROM mood_entries
GROUP BY day, user_id;
"""


STRESS_STRESSORS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stress_stressors (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


STRESS_ASSESSMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stress_assessments (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    score SMALLINT NOT NULL,
    qualitative_label TEXT NOT NULL,
    context_note TEXT NULL,
    expression_session_id BIGINT REFERENCES stress_expression_sessions(id) ON DELETE SET NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


STRESS_ASSESSMENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_assessments_user_created
    ON stress_assessments (user_id, created_at DESC);
"""


STRESS_EXPRESSION_SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stress_expression_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    capture_type TEXT,
    device_capabilities JSONB,
    status TEXT DEFAULT 'in_progress',
    metadata JSONB
);
"""


STRESS_EXPRESSION_SESSIONS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_expression_sessions_user_time
    ON stress_expression_sessions (user_id, started_at DESC);
"""


STRESS_ASSESSMENT_STRESSORS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stress_assessment_stressors (
    assessment_id BIGINT NOT NULL REFERENCES stress_assessments(id) ON DELETE CASCADE,
    stressor_id BIGINT NOT NULL REFERENCES stress_stressors(id) ON DELETE CASCADE,
    impact_level TEXT,
    impact_score NUMERIC(5,2),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (assessment_id, stressor_id)
);
"""


STRESS_ASSESSMENT_STRESSORS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_assessment_stressors_stressor
    ON stress_assessment_stressors (stressor_id);
"""


STRESS_EXPRESSION_METRICS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stress_expression_metrics (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES stress_expression_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    heart_rate_bpm NUMERIC(5,2),
    systolic_bp SMALLINT,
    diastolic_bp SMALLINT,
    breathing_rate NUMERIC(5,2),
    expression_primary TEXT,
    expression_confidence NUMERIC(4,3),
    stress_inference NUMERIC(5,2),
    metadata JSONB
);
"""


STRESS_EXPRESSION_METRICS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_expression_metrics_session_time
    ON stress_expression_metrics (session_id, captured_at);
"""


STRESS_EXPRESSION_METRICS_USER_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_expression_metrics_user_time
    ON stress_expression_metrics (user_id, captured_at DESC);
"""


STRESS_INSIGHTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stress_insights (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    insight_type TEXT NOT NULL,
    severity TEXT,
    title TEXT,
    description TEXT,
    suggested_action TEXT,
    status TEXT DEFAULT 'new',
    related_stressor_id BIGINT REFERENCES stress_stressors(id) ON DELETE SET NULL,
    first_detected_at TIMESTAMPTZ,
    last_occurrence_at TIMESTAMPTZ,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


STRESS_INSIGHTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_insights_user_created
    ON stress_insights (user_id, created_at DESC);
"""


STRESS_INSIGHTS_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_insights_status
    ON stress_insights (status);
"""


STRESS_INSIGHTS_TYPE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_stress_insights_type
    ON stress_insights (insight_type);
"""


STRESS_DAILY_STATS_VIEW_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS stress_daily_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', created_at) AS day,
    user_id,
    AVG(score)::numeric AS avg_score,
    COUNT(*) AS assessments,
    COUNT(DISTINCT sas.stressor_id) AS distinct_stressors,
    COUNT(*) FILTER (WHERE score >= 4) AS high_events,
    COUNT(*) FILTER (WHERE score >= 5) AS extreme_events
FROM stress_assessments sa
LEFT JOIN stress_assessment_stressors sas ON sas.assessment_id = sa.id
GROUP BY day, user_id;
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

        # Sleep tracking tables
        await conn.execute(SLEEP_SCHEDULE_TABLE_SQL)
        await conn.execute(SLEEP_SCHEDULE_INDEX_SQL)

        await conn.execute(SLEEP_SESSIONS_TABLE_SQL)
        await conn.execute(SLEEP_SESSIONS_START_INDEX_SQL)
        await conn.execute(SLEEP_SESSIONS_END_INDEX_SQL)
        await conn.execute(SLEEP_SESSIONS_ACTIVE_INDEX_SQL)

        await conn.execute(SLEEP_STAGES_TABLE_SQL)
        await conn.execute(SLEEP_STAGES_INDEX_SQL)

        await conn.execute(SLEEP_INSIGHTS_TABLE_SQL)
        await conn.execute(SLEEP_INSIGHTS_USER_INDEX_SQL)
        await conn.execute(SLEEP_INSIGHTS_TYPE_INDEX_SQL)
        await conn.execute(SLEEP_INSIGHTS_STATUS_INDEX_SQL)

        await conn.execute(SLEEP_EVENTS_TABLE_SQL)
        await conn.execute(SLEEP_EVENTS_INDEX_SQL)

        # Mood tracker tables
        await conn.execute(MOOD_ENTRIES_TABLE_SQL)
        await conn.execute(MOOD_ENTRIES_USER_CREATED_INDEX_SQL)
        await conn.execute(MOOD_ENTRIES_VALUE_INDEX_SQL)
        await conn.execute(MOOD_ENTRIES_IMPROVEMENT_INDEX_SQL)

        await conn.execute(MOOD_SUGGESTIONS_TABLE_SQL)
        await conn.execute(MOOD_SUGGESTIONS_USER_STATUS_INDEX_SQL)
        await conn.execute(MOOD_SUGGESTIONS_CREATED_INDEX_SQL)
        await conn.execute(MOOD_SUGGESTIONS_STATUS_PRIORITY_INDEX_SQL)

        # Stress management tables
        await conn.execute(STRESS_EXPRESSION_SESSIONS_TABLE_SQL)
        await conn.execute(STRESS_EXPRESSION_SESSIONS_INDEX_SQL)

        await conn.execute(STRESS_STRESSORS_TABLE_SQL)

        await conn.execute(STRESS_ASSESSMENTS_TABLE_SQL)
        await conn.execute(STRESS_ASSESSMENTS_INDEX_SQL)

        await conn.execute(STRESS_ASSESSMENT_STRESSORS_TABLE_SQL)
        await conn.execute(STRESS_ASSESSMENT_STRESSORS_INDEX_SQL)

        await conn.execute(STRESS_EXPRESSION_METRICS_TABLE_SQL)
        await conn.execute(STRESS_EXPRESSION_METRICS_INDEX_SQL)
        await conn.execute(STRESS_EXPRESSION_METRICS_USER_INDEX_SQL)

        await conn.execute(STRESS_INSIGHTS_TABLE_SQL)
        await conn.execute(STRESS_INSIGHTS_INDEX_SQL)
        await conn.execute(STRESS_INSIGHTS_STATUS_INDEX_SQL)
        await conn.execute(STRESS_INSIGHTS_TYPE_INDEX_SQL)
        
        

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
            await conn.execute(
                "SELECT create_hypertable('mood_entries','created_at', chunk_time_interval => INTERVAL '14 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
            )
            await conn.execute(
                "SELECT create_hypertable('stress_assessments','created_at', chunk_time_interval => INTERVAL '7 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
            )
            await conn.execute(
                "SELECT create_hypertable('stress_expression_metrics','captured_at', chunk_time_interval => INTERVAL '7 days', partitioning_column => 'user_id', number_partitions => 8, if_not_exists => TRUE);"
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
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_entries_metadata_gin ON mood_entries USING GIN (metadata);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_suggestions_tags_gin ON mood_suggestions USING GIN (tags);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_suggestions_metadata_gin ON mood_suggestions USING GIN (metadata);")

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
            await conn.execute(STRESS_DAILY_STATS_VIEW_SQL)
            await conn.execute(MOOD_DAILY_STATS_VIEW_SQL)
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
                await conn.execute(
                    """
                    CREATE MATERIALIZED VIEW IF NOT EXISTS stress_daily_stats AS
                    SELECT date_trunc('day', created_at) AS day,
                           user_id,
                           AVG(score)::numeric AS avg_score,
                           COUNT(*) AS assessments
                    FROM stress_assessments
                    GROUP BY day, user_id;
                    """
                )
                await conn.execute(
                    """
                    CREATE MATERIALIZED VIEW IF NOT EXISTS mood_daily_stats AS
                    SELECT date_trunc('day', created_at) AS day,
                           user_id,
                           AVG(mood_value)::float AS avg_mood_value,
                           COUNT(*) AS entries_count,
                           MIN(mood_value) AS min_mood_value,
                           MAX(mood_value) AS max_mood_value,
                           MAX(mood_value) - MIN(mood_value) AS mood_swing,
                           (ARRAY_AGG(mood_value ORDER BY created_at ASC))[1] AS first_mood_value,
                           (ARRAY_AGG(mood_value ORDER BY created_at DESC))[1] AS last_mood_value,
                           COUNT(*) FILTER (WHERE mood_value >= 3) AS positive_entries,
                           COUNT(*) FILTER (WHERE mood_value <= 2) AS negative_entries
                    FROM mood_entries
                    GROUP BY day, user_id;
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
            await conn.execute("ALTER TABLE stress_assessments SET (timescaledb.compress, timescaledb.compress_segmentby='user_id');")
            await conn.execute("ALTER TABLE stress_expression_metrics SET (timescaledb.compress, timescaledb.compress_segmentby='user_id');")
            await conn.execute("SELECT add_compression_policy('stress_assessments', INTERVAL '60 days');")
            await conn.execute("SELECT add_compression_policy('stress_expression_metrics', INTERVAL '30 days');")
        except Exception:
            pass

        # Refresh policies for continuous aggregates (if available)
        try:
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_behavior_scores', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');")
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_crisis_counts', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');")
            await conn.execute("SELECT add_continuous_aggregate_policy('daily_intent_counts', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '2 hours');")
            await conn.execute("SELECT add_continuous_aggregate_policy('mindful_daily_minutes', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '2 hours');")
            await conn.execute("SELECT add_continuous_aggregate_policy('stress_daily_stats', start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '2 hours');")
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
        "DROP MATERIALIZED VIEW IF EXISTS mood_daily_stats;",
        "DROP MATERIALIZED VIEW IF EXISTS daily_intent_counts;",
        "DROP MATERIALIZED VIEW IF EXISTS daily_crisis_counts;",
        "DROP MATERIALIZED VIEW IF EXISTS daily_behavior_scores;",
        "DROP TABLE IF EXISTS mood_suggestions CASCADE;",
        "DROP TABLE IF EXISTS mood_entries CASCADE;",
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


# Import mindful routes so FastAPI auto-registration executes when db is imported.
try:  # pragma: no cover - side effect import
    import routes.mindful_routes  # noqa: F401
except Exception:
    pass
# if __name__ == "__main__":
#     asyncio.run(drop_all_tables(confirm=True, drop_users=True))