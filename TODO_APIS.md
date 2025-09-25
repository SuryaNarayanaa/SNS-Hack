## Mindful Hours – Backend API & Data Model

End-to-end spec powering the Mindful Hours screens (dashboard, new exercise flow, live session, completion, history & stats).

### Table Summary (New)

1. mindfulness_sessions – one row per exercise session (core).
2. mindfulness_goals – catalog of selectable goals.
3. mindfulness_soundscapes – catalog of ambient sound loops.
4. mindfulness_session_events (optional granular timeline; can defer).
5. mindful_daily_minutes (continuous aggregate view – optional optimization).

#### mindfulness_sessions
| Column | Type | Notes |
| ------ | ---- | ----- |
| id | BIGSERIAL PK | |
| user_id | INT FK auth_users | cascade delete |
| exercise_type | TEXT | breathing | mindfulness | relax | sleep |
| goal_code | TEXT FK mindfulness_goals(code) | nullable |
| soundscape_id | BIGINT FK mindfulness_soundscapes(id) | nullable |
| planned_duration_seconds | INT | from client selection |
| start_at | TIMESTAMPTZ | default now() |
| end_at | TIMESTAMPTZ | set on completion / abandonment cleanup |
| actual_duration_seconds | INT | computed when completed |
| cycles_completed | INT | breathing cycles etc |
| rating_relaxation | SMALLINT 1–10 | user self‑report |
| rating_stress_before/after | SMALLINT 1–10 | |
| rating_mood_before/after | SMALLINT 1–10 | |
| score_restful | NUMERIC(5,2) | derived 0–100 |
| score_focus | NUMERIC(5,2) | derived 0–100 |
| tags | TEXT[] | free tagging |
| metadata | JSONB | breath pattern, device, etc |
| created_at | TIMESTAMPTZ | default now() |

Indexes: (user_id, start_at DESC), (exercise_type).

#### mindfulness_goals
code (PK), title, short_tagline, description, default_exercise_type, recommended_durations (INT[] minutes), recommended_soundscape_slugs (TEXT[]), metadata JSONB, created_at.

#### mindfulness_soundscapes
id PK, slug UNIQUE, name, description, audio_url, loop_seconds, is_active, created_at.

#### mindfulness_session_events (optional)
session_id FK, user_id FK, event_type (phase_start|breath_in|breath_out|pause|resume), numeric_value, text_value, occurred_at, metadata. Index (session_id, occurred_at).

#### mindful_daily_minutes (continuous aggregate)
Daily aggregated mindful minutes per exercise_type (see SQL in analytics section). Optional; fallback is on-the-fly aggregation.

---

### Endpoint Overview

All endpoints require Bearer auth (existing auth system) unless stated.

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| /mindful/catalog/goals | GET | List selectable goals |
| /mindful/catalog/soundscapes | GET | List active soundscapes |
| /mindful/sessions | POST | Start a new session |
| /mindful/sessions | GET | Paginated session history |
| /mindful/sessions/{id} | GET | Session detail |
| /mindful/sessions/{id}/progress | PATCH | Mid‑session progress update (optional) |
| /mindful/sessions/{id}/complete | PATCH | Complete + ratings + scores |
| /mindful/sessions/{id}/events | GET | (Optional) list granular events |
| /mindful/sessions/{id}/events | POST | (Optional) append event |
| /mindful/stats/overview | GET | Dashboard summary (totals, donut, streak) |
| /mindful/stats/daily | GET | Daily minutes time series |
| /mindful/sessions/active | GET | (Optional) currently active session |

---

### Detailed Specs

#### GET /mindful/catalog/goals
Response:
```
{ "items": [ { "code": "sleep_better", "title": "I want to sleep better", "short_tagline": "Improve nightly rest", "default_exercise_type": "sleep", "recommended_durations": [10,20,30], "recommended_soundscapes": ["zen-garden","mountain-stream"], "metadata": {"icon": "moon"} } ] }
```
Optional future query: ?exercise_type=breathing.

#### GET /mindful/catalog/soundscapes
Query: active (bool, default true)
Response: list of { id, slug, name, description, audio_url, loop_seconds }.

#### POST /mindful/sessions
Body:
```
{ "exercise_type": "breathing", "goal_code": "focus_better", "planned_duration_minutes": 25, "soundscape_id": 12, "metadata": {"breath_pattern": "4-7-8"} }
```
Creates row; returns id, exercise_type, goal_code, soundscape_id, planned_duration_seconds, start_at, status=in_progress.

#### GET /mindful/sessions
Query params: limit (default 20, max 100), offset (default 0), exercise_type?, goal_code?, range? (e.g. 30d). Returns items + next_offset.

#### GET /mindful/sessions/{id}
Full record (sanitize internal fields if needed).

#### PATCH /mindful/sessions/{id}/progress (optional)
Body (all optional): { cycles_completed, elapsed_seconds, metadata }. Ignores if session already completed.
Response: { status: "ok" }.

#### PATCH /mindful/sessions/{id}/complete
Body example:
```
{ "cycles_completed": 40, "rating_relaxation": 8, "rating_stress_before": 6, "rating_stress_after": 3, "rating_mood_before": 4, "rating_mood_after": 7, "metadata": {"notes": "Felt calmer"} }
```
Server computes:
* end_at (if null)
* actual_duration_seconds = end-start
* score_restful (formula below)
* score_focus (goal dependent)
Returns structured session including derived scores & ratings.

#### (Optional) Events
POST /mindful/sessions/{id}/events – Body { event_type, numeric_value?, text_value?, metadata? }
GET /mindful/sessions/{id}/events – Returns chronological items.

#### GET /mindful/stats/overview
Query: range (default 30d; accepts 7d, 30d, 90d, 1y)
Response example:
```
{
	"range": "30d",
	"total_minutes": 491.5,
	"total_hours": 8.19,
	"by_exercise_type": [ {"exercise_type":"breathing","minutes":120.0,"sessions":6}, ... ],
	"streak_days": 5,
	"sessions_count": 14,
	"avg_session_minutes": 35.1,
	"last_session": { "id":345, "exercise_type":"breathing", "end_at":"...", "minutes":24.9, "score_restful":82.5 }
}
```
Streak: compute contiguous days ending today with >=1 session (pull distinct dates and iterate backward).

#### GET /mindful/stats/daily
Query: days (default 30, max 180), exercise_type? (filter). Uses continuous aggregate if present else runtime aggregation.
Response: { "items": [ { "day": "2025-09-01", "minutes": 35.0, "exercise_type": "breathing" }, ... ] }

#### (Optional) GET /mindful/sessions/active
Returns the most recent session for user where end_at IS NULL.

---

### Derived Score Formulas (Initial)

```
delta_stress = (rating_stress_before - rating_stress_after) or 0
score_restful = clamp( 50 + delta_stress*5 + rating_relaxation*3 , 0, 100 )
score_focus (only if goal_code like 'focus%') = clamp( 40 + (actual_duration_seconds/planned_duration_seconds)*30 + ( (rating_mood_after-rating_mood_before) *5 ), 0, 100 )
```
Store computed numbers in session row for fast reads.

---

### Edge Cases & Policies
* Completing twice: second call returns already-completed record (idempotent) – do not recalc scores unless ratings changed.
* Abandoned sessions: background job may auto-complete sessions older than X hours (mark end_at=start_at + planned_duration if missing).
* Minimum duration threshold: exclude sessions < 60s from stats (or flag in metadata) – implement filter in aggregation query.
* Input validation: exercise_type whitelist; ratings 1–10; planned_duration_minutes positive.

---

### Minimal Seed Data (Example)
```
INSERT INTO mindfulness_goals (code,title,short_tagline,description,default_exercise_type,recommended_durations,recommended_soundscape_slugs)
VALUES
 ('sleep_better','I want to sleep better','Improve nightly rest','Support better sleep hygiene','sleep','{10,20,30}','{rainforest,zen-garden}'),
 ('reduce_stress','I want to reduce stress','Calm the mind','Lower acute stress through breathing','breathing','{5,10,15,25}','{zen-garden,mountain-stream}')
ON CONFLICT DO NOTHING;

INSERT INTO mindfulness_soundscapes (slug,name,description,audio_url,loop_seconds)
VALUES
 ('zen-garden','Zen Garden','Soft chimes and water','https://cdn/app/audio/zen-garden.mp3',90),
 ('mountain-stream','Mountain Stream','Flowing water ambience','https://cdn/app/audio/mountain-stream.mp3',120)
ON CONFLICT DO NOTHING;
```

---

### Implementation Order (Recommended)
1. Create tables + indexes (sessions, goals, soundscapes). Seed catalogs.
2. Implement POST /mindful/sessions & PATCH /complete.
3. Implement overview + daily stats queries.
4. Add history listing + detail.
5. (Optional) progress + events + active session endpoint.
6. Add continuous aggregate (mindful_daily_minutes) if Timescale available.

This spec is now ready for backend implementation & frontend integration.

-----------------------------------------------------

## Sleep Quality – Backend API & Data Model

End-to-end spec for the Sleep Quality screens (score gauge, calendar, session start/stop, schedule creator, wake summary, insights & filters).

### New Tables

1. sleep_schedule – user’s recurring target schedule.
2. sleep_sessions – each sleep attempt/night (in-bed interval / detected session).
3. sleep_stages – granular stage segments (REM / light / deep / awake etc.).
4. sleep_insights – AI / analytics generated suggestions & detections.
5. sleep_events (optional) – raw sensor / micro events (movement, snore spikes, heart rate anomalies).
6. sleep_daily_summary (continuous aggregate/materialized view) – per-day rollups (performance optimization).

#### sleep_schedule
| Column | Type | Notes |
| ------ | ---- | ----- |
| id | BIGSERIAL PK | |
| user_id | INT FK auth_users | |
| bedtime_local | TIME | Target sleep start local clock |
| wake_time_local | TIME | Target wake time local clock |
| timezone | TEXT | IANA zone (e.g. 'America/Los_Angeles') |
| active_days | SMALLINT[] | 0=Mon .. 6=Sun (or use bool[7]) |
| target_duration_minutes | INT | Desired total sleep (e.g. 480) |
| auto_set_alarm | BOOLEAN | Toggle from UI |
| show_stats_auto | BOOLEAN | Display stats automatically after wake |
| is_active | BOOLEAN | Current active schedule |
| metadata | JSONB | future extensibility |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |
Index: (user_id, is_active DESC).

#### sleep_sessions
| Column | Type | Notes |
| id | BIGSERIAL PK | |
| user_id | INT FK | |
| schedule_id | BIGINT FK sleep_schedule | nullable |
| start_at | TIMESTAMPTZ | when user pressed start / detected asleep |
| end_at | TIMESTAMPTZ | set at wake |
| in_bed_start_at | TIMESTAMPTZ | optional (if different from start) |
| in_bed_end_at | TIMESTAMPTZ | optional |
| total_duration_minutes | NUMERIC(6,2) | computed asleep time |
| time_in_bed_minutes | NUMERIC(6,2) | |
| sleep_efficiency | NUMERIC(5,2) | total_duration / time_in_bed *100 |
| latency_minutes | NUMERIC(5,2) | time to fall asleep |
| awakenings_count | INT | brief wake episodes |
| rem_minutes | NUMERIC(6,2) | |
| deep_minutes | NUMERIC(6,2) | |
| light_minutes | NUMERIC(6,2) | includes core/light |
| awake_minutes | NUMERIC(6,2) | during session |
| heart_rate_avg | NUMERIC(5,2) | optional |
| heart_rate_min | SMALLINT | |
| heart_rate_max | SMALLINT | |
| score_overall | NUMERIC(5,2) | 0–100 sleep score |
| quality_label | TEXT | e.g. poor | fair | good | excellent |
| irregularity_flag | BOOLEAN | large variance vs schedule |
| device_source | TEXT | manual|watch|ring|phone |
| is_auto | BOOLEAN | auto detected vs manual |
| metadata | JSONB | raw provider summary, breathing rate, etc |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |
Indexes: (user_id, start_at DESC), (user_id, end_at DESC), partial index WHERE end_at IS NULL for active session lookup.

#### sleep_stages
id, session_id FK, user_id FK, stage (rem|deep|light|awake), start_at, end_at, duration_seconds (computed), movement_index NUMERIC NULL, heart_rate_avg NUMERIC NULL, metadata JSONB. Index (session_id, start_at).

#### sleep_insights
| Column | Type | Notes |
| id | BIGSERIAL PK | |
| user_id | INT FK | |
| session_id | BIGINT FK sleep_sessions | nullable (general insight) |
| insight_type | TEXT | snoring | pillow | temperature | irregularity | heartbeat_irregularity | custom |
| severity | TEXT | info|low|moderate|high|critical |
| title | TEXT | short display |
| description | TEXT | detailed explanation |
| suggested_action | TEXT | optional guidance |
| status | TEXT | new|acknowledged|dismissed|resolved |
| metadata | JSONB | evidence metrics |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |
Indexes: (user_id, created_at DESC), (status), (insight_type).

#### sleep_events (optional)
session_id, user_id, event_type (movement|snore|heart_rate_spike|resp_anomaly), numeric_value, text_value, occurred_at, metadata. Index (session_id, occurred_at).

#### sleep_daily_summary (continuous aggregate)
Columns: day (date bucket), user_id, avg_score, total_minutes, rem_minutes, deep_minutes, light_minutes, awakenings, efficiency_avg. Built from sleep_sessions; fallback = dynamic aggregation when view absent.

---

### Endpoint Overview

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| /sleep/schedule | GET | Get active schedule |
| /sleep/schedule | POST | Create new schedule (deactivate previous) |
| /sleep/schedule/{id} | PATCH | Update schedule fields |
| /sleep/schedule/{id}/activate | PATCH | Toggle is_active |
| /sleep/sessions/start | POST | Begin a sleep session |
| /sleep/sessions/{id}/stage | PATCH | Append / finalize a stage segment (optional streaming) |
| /sleep/sessions/{id}/complete | PATCH | Mark session ended + compute scores |
| /sleep/sessions/{id} | GET | Session detail (with stage breakdown) |
| /sleep/sessions | GET | List sessions with filters (calendar/history) |
| /sleep/sessions/calendar | GET | Month view summary (durations + score per day) |
| /sleep/sessions/active | GET | Current in-progress session if any |
| /sleep/stats/overview | GET | Aggregate metrics for range (score gauge) |
| /sleep/stats/daily | GET | Daily durations/scores timeseries |
| /sleep/stats/stages | GET | Daily stacked stage durations |
| /sleep/insights | GET | List insights (filter by status/type/range) |
| /sleep/insights/{id} | PATCH | Update insight status (ack/dismiss) |
| /sleep/insights/suggestions | GET | AI suggestions subset (active + actionable) |
| /sleep/sessions/filter | GET | Advanced filter endpoint for Filter Sleep screen |

All require Bearer auth.

---

### Detailed Endpoint Specs

#### GET /sleep/schedule
Response:
```
{ "schedule": { "id": 7, "bedtime_local": "22:30:00", "wake_time_local": "06:30:00", "active_days": [0,1,2,3,4], "target_duration_minutes": 480, "timezone": "America/Los_Angeles", "auto_set_alarm": true, "show_stats_auto": true, "is_active": true } }
```

#### POST /sleep/schedule
Body:
```
{ "bedtime_local": "22:30", "wake_time_local": "06:30", "active_days": [0,1,2,3,4,6], "target_duration_minutes": 480, "timezone": "America/Los_Angeles", "auto_set_alarm": true, "show_stats_auto": true }
```
Deactivates previous active schedule. Returns created schedule.

#### PATCH /sleep/schedule/{id}
Body: any subset of schedule fields. Returns updated schedule.

#### PATCH /sleep/schedule/{id}/activate
Body: { "is_active": true }
Marks selected schedule active; others set false.

#### POST /sleep/sessions/start
Body:
```
{ "schedule_id": 7, "device_source": "watch", "in_bed_start_at": "2025-01-27T22:18:00Z", "metadata": {"battery": 0.71} }
```
Response: { id, start_at, schedule_id, status: "in_progress" }

#### PATCH /sleep/sessions/{id}/stage (optional streaming ingestion)
Body:
```
{ "stage": "rem", "start_at": "2025-01-28T02:05:00Z", "end_at": "2025-01-28T02:37:00Z", "movement_index": 0.12, "heart_rate_avg": 58 }
```
Creates a sleep_stages row (or merges if contiguous same stage). Response { status: "ok" }.

#### PATCH /sleep/sessions/{id}/complete
Body (optional overrides):
```
{ "end_at": "2025-01-28T06:15:00Z", "awake_minutes": 12, "metadata": {"alarm_triggered": true} }
```
Server computes stage totals, latency, efficiency, score_overall & quality_label. Idempotent (subsequent calls return final state).
Response (example):
```
{
	"id": 42,
	"start_at": "2025-01-27T22:32:11Z",
	"end_at": "2025-01-28T06:15:07Z",
	"total_duration_minutes": 495.0,
	"rem_minutes": 130.0,
	"deep_minutes": 85.0,
	"light_minutes": 280.0,
	"awake_minutes": 12.0,
	"sleep_efficiency": 92.4,
	"latency_minutes": 14.0,
	"awakenings_count": 3,
	"score_overall": 89.0,
	"quality_label": "good"
}
```

#### GET /sleep/sessions/{id}
Returns full session + stages array + associated insights (optional include_stages=false to suppress large payload).

#### GET /sleep/sessions
Query params:
* limit (default 20, max 100)
* offset (default 0)
* from (ISO date) optional
* to (ISO date) optional
* min_duration (minutes) optional
* has_insights (bool) optional
* stage (rem|deep|awake|light) optional (returns only sessions containing stage)
Response: { items: [...], next_offset: <int|null> }

#### GET /sleep/sessions/calendar
Query: month=YYYY-MM (default current month)
Response:
```
{ "month": "2025-01", "days": [ { "date": "2025-01-01", "duration_minutes": 430.0, "score": 78.0 }, ... ] }
```
Used to populate calendar heat / dots.

#### GET /sleep/sessions/active
Returns active session (where end_at IS NULL) or { "session": null }.

#### GET /sleep/stats/overview
Query: range=30d (supports 7d,30d,90d,180d,1y)
Response:
```
{
	"range": "30d",
	"average_score": 72.4,
	"score_delta_vs_prev_period": +8.1,
	"average_duration_minutes": 444.2,
	"target_duration_minutes": 480,
	"rem_pct": 22.5,
	"deep_pct": 16.8,
	"light_pct": 56.0,
	"awake_pct": 4.7,
	"regularity_minutes_stddev": 38.0,
	"efficiency_pct": 90.2,
	"streak_days_meeting_target": 5
}
```

#### GET /sleep/stats/daily
Query: days=30 (1–365)
Response: { "items": [ { "day": "2025-01-01", "duration_minutes": 430.0, "score": 78.0 }, ... ] }

#### GET /sleep/stats/stages
Query: days=30
Response: { "items": [ { "day": "2025-01-01", "rem": 80.0, "deep": 60.0, "light": 290.0, "awake": 15.0 }, ... ] }

#### GET /sleep/insights
Query params: status (comma list), type (comma list), range=30d, limit, offset.
Response: { "items": [ { "id":11, "insight_type":"snoring", "severity":"moderate", "title":"Loud Snoring", "status":"new", "session_id":42 } ] }

#### PATCH /sleep/insights/{id}
Body: { "status": "acknowledged" } OR { "status": "dismissed" }
Returns updated insight.

#### GET /sleep/insights/suggestions
Returns actionable insights (status=new or acknowledged) sorted by severity.

#### GET /sleep/sessions/filter
Advanced search (backing Filter Sleep UI).
Query params (all optional): from, to, min_duration, max_duration, type (exercise_type alias – ignore for sleep), stage, include_insights (bool), min_score, max_score.
Response similar to /sleep/sessions but guaranteed all applied filters echoed:
```
{ "filters": { "from": "2025-01-01", "to": "2025-01-31", "min_duration": 240, "stage": "rem" }, "items": [ ... ] }
```

---

### Aggregation & Scoring Formulas (Initial)

Let:
* target = schedule.target_duration_minutes (or default 480)
* dur = total_duration_minutes
* efficiency = sleep_efficiency (0–100)
* rem_ratio = rem_minutes / NULLIF(dur,0)
* deep_ratio = deep_minutes / NULLIF(dur,0)
* variance = stddev of midpoint sleep time (minutes) over range

Scores (scaled 0–100 then weighted):
```
duration_score = clamp( (dur / target) * 100, 0, 120 ) capped then rescaled to 0–100 (values >100 -> 100)
efficiency_score = clamp(efficiency, 0, 100)
rem_score = clamp( (rem_ratio / 0.22) * 100, 0, 130 ) -> min( value, 110 ) then scale to 0–100
deep_score = clamp( (deep_ratio / 0.18) * 100, 0, 130 ) -> min( value, 110 ) then scale to 0–100
regularity_score = clamp( 100 - (variance / 60 * 100), 0, 100 )  -- 60 min stddev => 0
disturbance_penalty = min( awakenings_count * 3, 25 )

raw = 0.3*duration_score + 0.2*efficiency_score + 0.15*rem_score + 0.15*deep_score + 0.15*regularity_score + 0.05*heart_rate_component - disturbance_penalty
score_overall = clamp(raw, 0, 100)
```
quality_label mapping: <50 poor, 50–65 fair, 65–80 good, >80 excellent.

Heart rate component optional (e.g., inverse of elevated average vs user baseline stored elsewhere; can start at neutral 50).

---

### Calendar & Daily Summary Logic
* Calendar endpoint groups sessions by date(start_at in user timezone) choose longest or merged contiguous sessions.
* If multiple segments (e.g., fragmentation), sum their durations for that date.
* sleep_daily_summary view (optional) pre-computes aggregated durations, stage totals, and average scores.

Continuous aggregate (Timescale example):
```
CREATE MATERIALIZED VIEW IF NOT EXISTS sleep_daily_summary
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', start_at) AS day,
			 user_id,
			 AVG(score_overall) AS avg_score,
			 SUM(total_duration_minutes) AS total_minutes,
			 SUM(rem_minutes) AS rem_minutes,
			 SUM(deep_minutes) AS deep_minutes,
			 SUM(light_minutes) AS light_minutes,
			 SUM(awake_minutes) AS awake_minutes,
			 AVG(sleep_efficiency) AS efficiency_avg,
			 SUM(awakenings_count) AS awakenings
FROM sleep_sessions
WHERE end_at IS NOT NULL
GROUP BY day, user_id;
```

---

### Edge Cases & Policies
* In-progress session older than 20h: auto-complete with end_at = start_at + detected stage end or truncate.
* Overlapping sessions: reject start if another active; allow manual override flag (metadata.manual_force=true).
* Stage segments must not overlap within same session (enforce in code, not DB for simplicity).
* Daylight Saving Time: store UTC; convert to user timezone for calendar & regularity variance.
* Deleting schedule should not orphan sessions (retain schedule_id; set ON DELETE SET NULL if schedule removed).
* If no stages ingested, treat entire (start_at,end_at) as light stage for metrics.

---

### Sample Seed (Optional)
```
INSERT INTO sleep_schedule (user_id, bedtime_local, wake_time_local, timezone, active_days, target_duration_minutes, auto_set_alarm, show_stats_auto, is_active)
VALUES (1,'22:30','06:30','America/Los_Angeles','{0,1,2,3,4,6}',480,true,true,true);
```

---

### Implementation Order
1. Tables: sleep_schedule, sleep_sessions, sleep_stages, sleep_insights (+ indexes).
2. Basic schedule CRUD + session start/complete endpoints.
3. Stage ingestion (optional early if devices feed data).
4. Overview + daily stats + calendar queries.
5. Insights generation logic (initial: derive irregularity/snoring placeholders) + endpoints.
6. Advanced filter endpoint & continuous aggregate optimization.
7. Scoring refinement & personalization.

This Sleep Quality spec is ready for backend implementation.



## Stress Management – Backend API & Data Model

Comprehensive spec for Stress Management screens (current level gauge, daily self‑report flow, stressor selection, optional expression/biometric capture, confirmation, and stats screen with bubbles + trends).

### Data Modeling Strategy
You can reuse existing `behavioral_events` for generic logging, but purpose‑built tables below give faster aggregated queries & clearer semantics. You may still dual‑write a simplified event into `behavioral_events` (event_type = 'stress_rating') for unified analytics.

### New Tables
1. stress_assessments – one row per user self‑reported stress instance (core numeric score 0–5 or 1–5).
2. stress_stressors – catalog of selectable stressor categories.
3. stress_assessment_stressors – join table linking assessment to chosen stressors + computed impact classification.
4. stress_expression_sessions – optional recording/analysis session (video / sensor capture) tied to an assessment or standalone.
5. stress_expression_metrics – time‑series / snapshot biometric & expression metrics captured during an expression session.
6. stress_insights – AI summary / anomaly detections (e.g., consistently high evening stress, specific stressor escalation).
7. stress_daily_stats (continuous aggregate / materialized view) – per‑day aggregated average score, count, unique stressors, etc. (Optional; fallback = on‑the‑fly aggregation.)

#### stress_assessments
| Column | Type | Notes |
| ------ | ---- | ----- |
| id | BIGSERIAL PK | |
| user_id | INT FK auth_users | |
| score | SMALLINT | 0–5 or 1–5 scale (UI uses 0–5 gauge; decide & stay consistent) |
| qualitative_label | TEXT | calm|normal|elevated|high|extreme (derived) |
| context_note | TEXT | optional user freeform note |
| expression_session_id | BIGINT FK stress_expression_sessions | nullable |
| created_at | TIMESTAMPTZ DEFAULT now() | timestamp of submission |
| metadata | JSONB | device, location (if consent), app_version |
Index: (user_id, created_at DESC).

#### stress_stressors
| Column | Type | Notes |
| id | BIGSERIAL PK | |
| slug | TEXT UNIQUE | e.g., 'work', 'finance', 'loneliness', 'relationship', 'health', 'kids', 'other' |
| name | TEXT | Display name |
| description | TEXT | Optional longer copy |
| is_active | BOOLEAN DEFAULT TRUE | |
| created_at | TIMESTAMPTZ | |
| metadata | JSONB | color, icon, default_impact_weights |

#### stress_assessment_stressors
| Column | Type | Notes |
| assessment_id | BIGINT FK stress_assessments(id) ON DELETE CASCADE | PK part |
| stressor_id | BIGINT FK stress_stressors(id) ON DELETE CASCADE | PK part |
| impact_level | TEXT | low|moderate|high|very_high (AI or heuristic) |
| impact_score | NUMERIC(5,2) | normalized 0–1 for weighting |
| metadata | JSONB | explanation, model_confidence |
Primary key (assessment_id, stressor_id).

#### stress_expression_sessions
| Column | Type | Notes |
| id | BIGSERIAL PK | |
| user_id | INT FK | |
| started_at | TIMESTAMPTZ DEFAULT now() | |
| completed_at | TIMESTAMPTZ | |
| capture_type | TEXT | 'camera' | 'sensor' | 'combined' |
| device_capabilities | JSONB | resolution, permissions, etc |
| status | TEXT | in_progress|completed|aborted |
| metadata | JSONB | model versions, environment hints |

#### stress_expression_metrics
| Column | Type | Notes |
| id | BIGSERIAL PK | |
| session_id | BIGINT FK stress_expression_sessions(id) ON DELETE CASCADE | |
| user_id | INT FK | redundancy for faster filtering |
| captured_at | TIMESTAMPTZ DEFAULT now() | |
| heart_rate_bpm | NUMERIC(5,2) | nullable |
| systolic_bp | SMALLINT | nullable |
| diastolic_bp | SMALLINT | nullable |
| breathing_rate | NUMERIC(5,2) | breaths per minute |
| expression_primary | TEXT | e.g., neutral|sad|angry|fear|surprise|
| expression_confidence | NUMERIC(4,3) | 0–1 |
| stress_inference | NUMERIC(5,2) | model output 0–100 (optional) |
| metadata | JSONB | facial landmarks, quality flags |
Index: (session_id, captured_at), (user_id, captured_at DESC).

#### stress_insights
| Column | Type | Notes |
| id | BIGSERIAL PK | |
| user_id | INT FK | |
| insight_type | TEXT | trend_increase|evening_spike|single_stressor_dominant|irregular_pattern|improvement |
| severity | TEXT | info|low|moderate|high |
| title | TEXT | short heading |
| description | TEXT | detail |
| suggested_action | TEXT | guidance |
| status | TEXT | new|acknowledged|dismissed|resolved |
| related_stressor_id | BIGINT FK stress_stressors | nullable |
| first_detected_at | TIMESTAMPTZ | |
| last_occurrence_at | TIMESTAMPTZ | |
| metadata | JSONB | underlying stats |
| created_at | TIMESTAMPTZ DEFAULT now() | |
| updated_at | TIMESTAMPTZ DEFAULT now() | |
Indexes: (user_id, created_at DESC), (status), (insight_type).

#### stress_daily_stats (optional continuous aggregate)
Columns: day (date), user_id, avg_score, assessments, distinct_stressors, high_events (count score>=4), extreme_events (score>=5), dominant_stressor_id.

---

### Endpoint Overview
All endpoints require Bearer auth.

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| /stress/stressors/catalog | GET | List selectable stressors |
| /stress/assessment | POST | Submit a new stress assessment (with optional stressors & expression session id) |
| /stress/assessments | GET | List assessments (pagination + filters) |
| /stress/assessments/recent | GET | Latest N assessments (quick gauge history) |
| /stress/assessments/{id} | GET | Detailed assessment + stressors + expression summary |
| /stress/summary/overview | GET | Current score + trend + top stressors |
| /stress/stats/daily | GET | Daily aggregated scores (line) |
| /stress/stats/stressors | GET | Aggregated impact per stressor (bubble sizes) |
| /stress/expression/start | POST | Begin expression/biometric capture session |
| /stress/expression/{id}/metrics | PATCH | Append metrics snapshot (batch or single) |
| /stress/expression/{id}/complete | PATCH | Finish session + return aggregated metrics |
| /stress/expression/{id} | GET | Session detail with optional metrics (paginate) |
| /stress/insights | GET | List insights (filter severity/status/range) |
| /stress/insights/{id} | PATCH | Update status (ack/dismiss) |

Optional convenience:
| /stress/assessments/trend | GET | Rolling averages & slopes |
| /stress/expression/recent | GET | Last completed expression session |

---

### Detailed Endpoint Specs

#### GET /stress/stressors/catalog
Query params: active (bool default true)
Response:
```
{ "items": [ { "id": 3, "slug": "loneliness", "name": "Loneliness", "metadata": {"icon":"leaf","color":"#8CB870"} } ] }
```

#### POST /stress/assessment
Body:
```
{
	"score": 3,
	"stressor_slugs": ["loneliness","work"],
	"context_note": "After long remote day",
	"expression_session_id": 55,
	"metadata": {"time_of_day":"evening"}
}
```
Server logic:
1. Insert assessment row with derived qualitative_label.
2. Map provided slugs -> stressor ids, insert into join table (impact initially null).
3. Optionally enqueue background task to classify impact scores (model) and update join rows.
Response:
```
{ "id": 1201, "score": 3, "qualitative_label": "elevated", "created_at": "...", "stressors": [ {"slug":"loneliness"}, {"slug":"work"} ] }
```

#### GET /stress/assessments
Query params:
* limit (default 30, max 100)
* offset (default 0)
* from (ISO date) optional
* to (ISO date) optional
* min_score / max_score
* stressor (slug) – filter assessments containing that stressor
Response:
```
{ "items": [ {"id":1201,"score":3,"qualitative_label":"elevated","created_at":"..."} ], "next_offset": 30 }
```

#### GET /stress/assessments/recent
Query: limit=10 (max 50)
Returns chronological descending limited subset for small sparkline.

#### GET /stress/assessments/{id}
Response includes assessment, stressors (with impact_score/impact_level if available), and linked expression_session summary.

#### GET /stress/summary/overview
Purpose: Single dashboard call for current level card + bubble stats.
Query: range=30d (7d|14d|30d|90d)
Response example:
```
{
	"current": { "score": 3, "qualitative_label": "elevated", "created_at": "..." },
	"trend": { "direction": "up", "slope": 0.12, "delta_vs_prev_period": +0.4 },
	"top_stressors": [ { "slug":"loneliness", "avg_score": 3.8, "impact_level":"very_high" }, { "slug":"work", "avg_score": 2.9 } ],
	"distribution": { "calm": 5, "normal": 12, "elevated": 8, "high": 3, "extreme": 1 }
}
```

#### GET /stress/stats/daily
Query: days=30 (1–180)
Response: `{ "items": [ { "day": "2025-09-01", "avg_score": 2.6, "assessments": 3 }, ... ] }`
Uses `stress_daily_stats` view if present; fallback raw aggregation:
```
SELECT date(created_at) AS day,
			 AVG(score)::float AS avg_score,
			 COUNT(*) AS assessments
FROM stress_assessments
WHERE user_id=$1 AND created_at >= now() - $2::interval
GROUP BY 1 ORDER BY 1;
```

#### GET /stress/stats/stressors
Query: days=30, limit=10
Response:
```
{ "items": [ { "slug":"loneliness", "assessments": 14, "avg_score": 3.8, "avg_impact_score": 0.72 }, ... ] }
```
SQL sketch (join & aggregate):
```
SELECT s.slug,
			 COUNT(DISTINCT a.id) AS assessments,
			 AVG(a.score)::float AS avg_score,
			 AVG(sas.impact_score)::float AS avg_impact_score
FROM stress_assessments a
JOIN stress_assessment_stressors sas ON sas.assessment_id=a.id
JOIN stress_stressors s ON s.id=sas.stressor_id
WHERE a.user_id=$1 AND a.created_at >= now() - $2::interval
GROUP BY s.slug
ORDER BY avg_impact_score DESC NULLS LAST, avg_score DESC
LIMIT $3;
```

#### POST /stress/expression/start
Body:
```
{ "capture_type": "camera", "metadata": {"resolution":"720p"} }
```
Response: `{ "id": 55, "started_at": "...", "status": "in_progress" }`

#### PATCH /stress/expression/{id}/metrics
Body (single or batch):
```
{ "heart_rate_bpm": 68, "systolic_bp": 134, "diastolic_bp": 82, "expression_primary": "neutral", "expression_confidence": 0.91, "stress_inference": 47.2 }
```
Accept array variant: `{ "items": [ {...}, {...} ] }`
Response: `{ "status": "ok", "accepted": N }`

#### PATCH /stress/expression/{id}/complete
Body (optional): `{ "metadata": {"quality":"good_lighting"} }`
Server sets completed_at, aggregates average heart_rate, mean stress_inference etc.
Response:
```
{ "id":55, "completed_at":"...", "avg_heart_rate":67.4, "avg_stress_inference":45.1, "samples": 42, "status":"completed" }
```

#### GET /stress/expression/{id}
Query: include_metrics=false|true (default false), metrics_limit=100, metrics_offset=0
Response: base session plus optional metrics page.

#### GET /stress/insights
Query: status (list), type (list), days=60, limit, offset.
Response: `{ "items": [ { "id":9, "insight_type":"trend_increase", "severity":"moderate", "title":"Stress trending up evenings", "status":"new" } ] }`

#### PATCH /stress/insights/{id}
Body: `{ "status": "acknowledged" }` – returns updated record.

---

### Scoring & Label Logic
Base scale: integer score 0–5 (0 calm → 5 extreme) or 1–5. Choose ONE; mapping below assumes 0–5.
```
0 calm
1 normal
2 elevated (mild)
3 elevated (moderate)
4 high
5 extreme
```
Where UI compresses 2 & 3 into dynamic styling; keep both for analytics if desired.

Trend slope: compute linear regression slope over last N days (e.g., 14). direction = 'up' if slope > epsilon, 'down' if < -epsilon.

Impact classification (background job): For each assessment's chosen stressors:
```
impact_score = (assessment_score / 5) * weight_stressor (default 1) * recency_factor
impact_level buckets:
	>=0.75 very_high
	>=0.55 high
	>=0.35 moderate
	else low
```

Expression session aggregation example:
```
avg_stress_inference = AVG(stress_inference)
peak_heart_rate = MAX(heart_rate_bpm)
session_stress_delta = (last(stress_inference) - first(stress_inference))
```
Store in `stress_expression_sessions.metadata` for quick retrieval.

---

### Edge Cases & Policies
* Multiple assessments per day allowed; latest used as 'current'.
* Late entries (backdated) – allow `metadata.submitted_for` date; exclude from trend if older than range.
* Orphan expression sessions (user abandons) – cron to mark status=aborted if >30 mins without metrics & not completed.
* Metrics ingestion burst: accept batch array to reduce network overhead.
* Privacy: sensitive biometric raw frames not stored (only derived metrics & aggregate inference numbers).
* Deleting assessment cascades join table; do NOT cascade delete expression session (retain anonymized metrics) unless required by policy.

---

### Minimal Seed Data (Catalog)
```
INSERT INTO stress_stressors (slug,name) VALUES
 ('work','Work'),
 ('loneliness','Loneliness'),
 ('finance','Finance'),
 ('relationship','Relationship'),
 ('health','Health'),
 ('kids','Kids'),
 ('other','Other')
ON CONFLICT (slug) DO NOTHING;
```

---

### Implementation Order
1. Tables: stress_stressors, stress_assessments, stress_assessment_stressors.
2. POST /stress/assessment + catalog endpoint.
3. Overview + daily stats endpoints (simple SQL aggregation).
4. Expression session + metrics ingestion (if feature enabled) – with rate limits.
5. Stressor impact background classification & /stress/stats/stressors.
6. Insights detection & endpoints.
7. Continuous aggregate view & trend slope optimization.

This Stress Management spec is ready for backend implementation.

----------------------------------------------

## Mood Tracker – Backend API & Data Model

End-to-end spec for Mood Tracker screens (current mood card, stats graph with range toggles, mood entry flow, history list with filters, and AI Suggestions tab).

### Data Modeling Strategy
Simple append-only mood entries drive all charts. Aggregations (daily averages, distribution, swing) can be computed on-the-fly or accelerated via a continuous aggregate view. AI suggestions stored separately and life-cycled via status field.

### New Tables
1. mood_entries – core mood self-report records.
2. mood_suggestions – AI / rule-based actionable suggestions ("Do Positive Activity").
3. mood_daily_stats (continuous aggregate / materialized view, optional) – per-day rollups (avg, swing, counts).
4. (Optional) mood_entry_tags + mood_tags – only if freeform tagging or categorical context chips are later required (deferred for now).

#### mood_entries
| Column | Type | Notes |
| ------ | ---- | ----- |
| id | BIGSERIAL PK | |
| user_id | INT FK auth_users | |
| mood_value | SMALLINT | 0–5 scale (see mapping below) |
| mood_label | TEXT | cached label from mapping (redundant for speed) |
| note | TEXT | optional user reflection |
| improvement_flag | BOOLEAN | user indicated improvement vs previous entry (client logic) |
| created_at | TIMESTAMPTZ DEFAULT now() | submission timestamp |
| metadata | JSONB | time_of_day, location (if consent), device |
Index: (user_id, created_at DESC), (user_id, mood_value), partial index WHERE improvement_flag IS TRUE.

#### mood_suggestions
| Column | Type | Notes |
| ------ | ---- | ----- |
| id | BIGSERIAL PK | |
| user_id | INT FK | |
| suggestion_type | TEXT | acknowledge_feeling | positive_activity | seek_support | journaling | gratitude | sleep_hygiene | custom |
| title | TEXT | short heading |
| description | TEXT | detailed explanation |
| tags | TEXT[] | e.g., {"walking","breathing"} |
| priority | SMALLINT | 1(high)-5(low) default 3 |
| status | TEXT | new|acknowledged|dismissed|completed |
| resolved_at | TIMESTAMPTZ | when completed/dismissed |
| metadata | JSONB | model evidence, scores |
| created_at | TIMESTAMPTZ DEFAULT now() | |
| updated_at | TIMESTAMPTZ DEFAULT now() | |
Indexes: (user_id, status), (user_id, created_at DESC), (status, priority DESC).

#### mood_daily_stats (optional continuous aggregate)
Columns: day (date), user_id, avg_mood_value, entries_count, min_mood_value, max_mood_value, mood_swing (max-min), first_mood_value, last_mood_value, positive_entries (value>=3), negative_entries (value<=2).

Continuous aggregate sketch (Timescale):
```
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
```

### Mood Scale Mapping (0–5)
```
0 depressed
1 sad
2 neutral
3 happy
4 joyful
5 overjoyed
```
Store both numeric value and label (cached). Frontend can collapse 4 & 5 if needed for bar charts.

### Endpoint Overview
All endpoints require Bearer auth.

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| /mood/entries | POST | Create a new mood entry |
| /mood/entries | GET | List mood entries (history) with filters |
| /mood/entries/recent | GET | Recent N entries for sparkline |
| /mood/entries/{id} | GET | Entry detail |
| /mood/entries/{id} | PATCH | Update note / improvement flag |
| /mood/entries/{id} | DELETE | Delete an entry (optional, soft delete alt) |
| /mood/summary/overview | GET | Current mood + distribution + trend |
| /mood/stats/daily | GET | Daily average & swing time series |
| /mood/stats/distribution | GET | Counts per mood label over range |
| /mood/entries/filter | GET | Advanced filter for Filter Mood screen |
| /mood/suggestions | GET | List AI suggestions |
| /mood/suggestions/{id} | PATCH | Update suggestion status |
| /mood/suggestions/active | GET | Actionable suggestions (status=new|acknowledged) |

---

### Detailed Endpoint Specs

#### POST /mood/entries
Body:
```
{ "mood_value": 3, "note": "Good run", "improvement_flag": true, "metadata": {"time_of_day":"morning"} }
```
Server sets mood_label from mapping.
Response:
```
{ "id": 501, "mood_value": 3, "mood_label": "happy", "created_at": "...", "improvement_flag": true }
```

#### GET /mood/entries
Query params: limit (default 30, max 100), offset (default 0), from (ISO date), to (ISO date), mood_min, mood_max, improvement (bool), order=desc|asc (created_at).
Response:
```
{ "items": [ {"id":501,"mood_value":3,"mood_label":"happy","created_at":"..."} ], "next_offset": 30 }
```

#### GET /mood/entries/recent
Query: limit=14 (max 60)
Returns chronological descending (or specify ?order=asc for graph-ready sequence).
```
{ "items": [ {"mood_value":4,"created_at":"..."}, ... ] }
```

#### GET /mood/entries/{id}
Returns full record including note & metadata.

#### PATCH /mood/entries/{id}
Body (any subset): `{ "note": "Felt better after walk", "improvement_flag": true }`
Response: updated record.

#### DELETE /mood/entries/{id}
Response: `{ "status":"deleted" }` (or implement soft delete by adding deleted_at column if compliance needed later).

#### GET /mood/summary/overview
Purpose: Single call for main dashboard.
Query: range=30d (supports 7d,14d,30d,90d,1y,all)
Response example:
```
{
	"range": "30d",
	"current": { "mood_value": 4, "mood_label": "joyful", "created_at": "..." },
	"trend": { "direction": "up", "slope": 0.18, "delta_vs_prev_period": +0.6 },
	"distribution": { "depressed":2, "sad":5, "neutral":9, "happy":11, "joyful":6, "overjoyed":3 },
	"avg_mood": 3.1,
	"mood_swing": 5,  
	"improvement_entries": 8
}
```
Trend slope computed via linear regression over daily avg values in range.

#### GET /mood/stats/daily
Query: days=30 (1–365) – uses `mood_daily_stats` if present else:
```
SELECT date(created_at) AS day,
			 AVG(mood_value)::float AS avg_mood_value,
			 (MAX(mood_value)-MIN(mood_value)) AS mood_swing,
			 COUNT(*) AS entries
FROM mood_entries
WHERE user_id=$1 AND created_at >= now() - ($2 || ' days')::interval
GROUP BY 1 ORDER BY 1;
```
Response:
```
{ "items": [ { "day":"2025-09-01", "avg_mood_value":3.2, "mood_swing":2, "entries":4 }, ... ] }
```

#### GET /mood/stats/distribution
Query: range=30d
Response:
```
{ "range":"30d", "counts": { "depressed":2, "sad":5, "neutral":9, "happy":11, "joyful":6, "overjoyed":3 } }
```

#### GET /mood/entries/filter
Supports Filter Mood screen.
Query params (all optional): from, to, mood_min, mood_max, improvement (bool), swing_min, swing_max (applies to per-day mood swing aggregation), include_notes (bool default false).
Response mirrors /mood/entries plus echo of applied filters:
```
{ "filters": {"from":"2025-09-01","mood_min":2}, "items": [ ... ] }
```

#### GET /mood/suggestions
Query params: status (comma list), type (comma list), range=30d, limit (default 20, max 100), offset (default 0).
Response:
```
{ "items": [ { "id":11, "suggestion_type":"positive_activity", "title":"Take a short walk", "status":"new", "tags":["walking"] } ], "next_offset": 20 }
```

#### PATCH /mood/suggestions/{id}
Body: `{ "status": "acknowledged" }` or `{ "status": "completed" }` – sets resolved_at if status in (completed,dismissed).
Response: updated suggestion.

#### GET /mood/suggestions/active
Returns actionable suggestions (status=new|acknowledged) sorted by priority then created_at.

---

### Aggregations & Formulas
Mood swing (per day): `max_mood_value - min_mood_value`.
Trend slope: linear regression slope of (day_index, avg_mood_value) over selected range; direction rule: > +0.05 up, < -0.05 down else flat.
Delta vs previous period: compare average mood of range vs preceding equal-length period.
Improvement count: number of entries with improvement_flag=TRUE in range.

### Edge Cases & Policies
* Multiple entries close in time allowed; frontend dedup logic optional (e.g., ignore if last entry < 5 minutes unless mood_value changed).
* Deleting an entry re-triggers cached aggregates (invalidate materialized view refresh or mark for recompute).
* If no entries in range, return empty counts and null trend.
* Large ranges (all) fallback to streaming query with limit; encourage pagination for /mood/entries.
* Timezone: store UTC; client aggregates by user timezone if cross-day boundary important for daily charts.
* Write amplification: optional dual-write simple event into `behavioral_events` (event_type='mood_entry', value=mood_value) for cross-domain analytics.

### Minimal Seed Data (Suggestions Examples)
```
INSERT INTO mood_suggestions (user_id,suggestion_type,title,description,tags,status,priority)
VALUES
 (1,'acknowledge_feeling','Acknowledge Feeling','Take a moment to label your emotion clearly',ARRAY['mindfulness'],'new',2),
 (1,'positive_activity','Do Positive Activity','Engage in a short walk outside for sunlight boost',ARRAY['walking'],'new',3)
ON CONFLICT DO NOTHING;
```

### Implementation Order
1. Create `mood_entries` + indexes.
2. Implement POST/GET /mood/entries & recent endpoint.
3. Add overview + daily stats aggregations (materialized view optional).
4. Add distribution + filter endpoints.
5. Create `mood_suggestions` & suggestion endpoints (basic rule-based seed first, AI later).
6. Add continuous aggregate `mood_daily_stats` and background refresh.
7. Optimize trend calculations with cached table if performance needed.

This Mood Tracker spec is ready for backend implementation & frontend integration.

----------------------------------------------

