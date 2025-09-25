# Mindful Goals & Soundscapes Reference

This note captures everything the frontend needs to integrate the catalog APIs that back the Mindful Hours goal picker and soundscape selector. It covers the request workflow, payloads, table schemas, and the product moments where each call should fire.

## Authentication

All endpoints described here live under `/mindful/*` and require a valid Bearer token. Reuse the shared auth interceptor so every request carries:

```
Authorization: Bearer <session_token>
Content-Type: application/json
```

If the header is missing or the token has expired, the API responds with `401 Unauthorized` and no body.

## Endpoint Summary

| Endpoint | Method | Purpose | Typical UI Touchpoint |
|----------|--------|---------|------------------------|
| `/mindful/catalog/goals` | `GET` | Retrieve the selectable mindfulness goals | Goal picker when starting a session, or resolving `goal_code` in history views |
| `/mindful/catalog/soundscapes` | `GET` | List available ambient soundscapes | Soundscape selector in pre-session setup, or rendering session history |

Both endpoints are read-only and safe to cache aggressively on the client.

---

## GET `/mindful/catalog/goals`

### What it does

Returns the catalog of mindfulness goals a user can select before starting an exercise. Each record includes presentation metadata plus recommended durations and soundscapes.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `exercise_type` | string | `null` | Optional filter for goals whose default exercise type matches one of `breathing`, `mindfulness`, `relax`, `sleep`. Case-sensitive. |

### Example Request

```
GET /mindful/catalog/goals?exercise_type=sleep
Authorization: Bearer <token>
```

```powershell
curl -H "Authorization: Bearer $env:TOKEN" `
		 "https://api.example.com/mindful/catalog/goals?exercise_type=sleep"
```

### Example Response

```json
{
	"items": [
		{
			"code": "sleep_better",
			"title": "I want to sleep better",
			"short_tagline": "Improve nightly rest",
			"description": "Support better sleep hygiene",
			"default_exercise_type": "sleep",
			"recommended_durations": [10, 20, 30],
			"recommended_soundscape_slugs": ["rainforest", "zen-garden"],
			"metadata": {
				"icon": "moon"
			}
		}
	]
}
```

### Backend Table: `mindfulness_goals`

| Column | Type | Notes |
|--------|------|-------|
| `code` | `TEXT PRIMARY KEY` | Stable identifier referenced by sessions (`goal_code`). |
| `title` | `TEXT NOT NULL` | Render as the primary label. |
| `short_tagline` | `TEXT` | Secondary line in the card. |
| `description` | `TEXT` | Longer copy for detail views/tooltips. |
| `default_exercise_type` | `TEXT NOT NULL` | One of the four supported exercise types. Useful for tab filtering. |
| `recommended_durations` | `INTEGER[]` | Minutes. Populate quick-select chips. |
| `recommended_soundscape_slugs` | `TEXT[]` | Maps to `mindfulness_soundscapes.slug`. |
| `metadata` | `JSONB` | Arbitrary display hints (icons, badges, etc.). |
| `created_at` | `TIMESTAMPTZ` | Auto-managed. |

**Sample Row**

```sql
INSERT INTO mindfulness_goals
(code, title, short_tagline, description, default_exercise_type,
 recommended_durations, recommended_soundscape_slugs, metadata)
VALUES (
	'sleep_better',
	'I want to sleep better',
	'Improve nightly rest',
	'Support better sleep hygiene',
	'sleep',
	'{10,20,30}',
	'{rainforest,zen-garden}',
	'{"icon": "moon"}'
);
```

### When to call it

- **Goal selection screen:** Fire on initial mount. If tabs are pre-filtered by exercise type, pass the tab’s type in the query.
- **Session recap/history:** When rendering past sessions, use cached catalog data to transform `goal_code` into user-facing text.
- **Background refresh:** Because the catalog rarely changes, refresh once per app launch or when the user explicitly pulls to refresh.

---

## GET `/mindful/catalog/soundscapes`

### What it does

Returns available ambient loops for playback during a session. By default it only returns active tracks.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `active` | boolean | `true` | `true` for active soundscapes, `false` for archived ones, `null` (omit param) to fetch all. |

### Example Request

```
GET /mindful/catalog/soundscapes?active=true
Authorization: Bearer <token>
```

```powershell
curl -H "Authorization: Bearer $env:TOKEN" `
		 "https://api.example.com/mindful/catalog/soundscapes?active=true"
```

### Example Response

```json
{
	"items": [
		{
			"id": 12,
			"slug": "zen-garden",
			"name": "Zen Garden",
			"description": "Soft chimes and water",
			"audio_url": "https://cdn/app/audio/zen-garden.mp3",
			"loop_seconds": 90,
			"is_active": true
		}
	]
}
```

### Backend Table: `mindfulness_soundscapes`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL PRIMARY KEY` | Use as the foreign key (`soundscape_id`) in sessions. |
| `slug` | `TEXT UNIQUE NOT NULL` | Stable identifier referenced in goal metadata. |
| `name` | `TEXT NOT NULL` | Display label. |
| `description` | `TEXT` | Optional copy. |
| `audio_url` | `TEXT NOT NULL` | Streaming source. |
| `loop_seconds` | `INTEGER` | Loop length in seconds for UI cues. |
| `is_active` | `BOOLEAN DEFAULT TRUE` | Toggle to hide from default catalog. |
| `created_at` | `TIMESTAMPTZ` | Auto-managed. |

**Sample Row**

```sql
INSERT INTO mindfulness_soundscapes
(slug, name, description, audio_url, loop_seconds, is_active)
VALUES (
	'zen-garden',
	'Zen Garden',
	'Soft chimes and water',
	'https://cdn/app/audio/zen-garden.mp3',
	90,
	TRUE
);
```

### When to call it

- **Soundscape picker (pre-session):** Fetch when the user toggles the “Add ambience” panel. Cache results locally—top-level loops change infrequently.
- **Session detail/history:** Use cached records to display the soundscape name or play preview buttons for past sessions.
- **Admin preview tools:** To expose archived/coming-soon loops, call with `?active=false` and render them in a separate section.

---

## Frontend Integration Tips

- **Caching:** Because catalogs are mostly static, memoize them via React Query/SWR or store in global state. Consider revalidation every few hours.
- **Error handling:** On `401` prompt for re-authentication. On `5xx` show a retry CTA; the API never mutates state so safe to retry.
- **Joining data:** Sessions reference `goal_code` and `soundscape_id`. After fetching catalogs, create lookup maps (`code → goal`, `id → soundscape`) to avoid repeated network calls when rendering history or stats.
- **Accessibility:** The responses include enough metadata to provide descriptive labels and tooltips—wire `short_tagline`/`description` through to screen readers.

Keep this file updated if new fields are added or additional filters are introduced.

---

## POST `/mindful/sessions`

### What it does

Creates a new mindfulness session record with the provided parameters. Returns the full session object including computed fields like status and planned duration in minutes.

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `exercise_type` | string | Yes | One of `breathing`, `mindfulness`, `relax`, `sleep`. |
| `planned_duration_minutes` | int | Yes | 1-240 minutes. |
| `goal_code` | string | No | References `mindfulness_goals.code`. |
| `soundscape_id` | int | No | References `mindfulness_soundscapes.id`. |
| `metadata` | object | No | Arbitrary JSON. |
| `tags` | array of strings | No | Free-form tags. |

### Example Request

```
POST /mindful/sessions
Authorization: Bearer <token>
Content-Type: application/json

{
  "exercise_type": "breathing",
  "goal_code": "focus_better",
  "planned_duration_minutes": 25,
  "soundscape_id": 12,
  "metadata": {"breath_pattern": "4-7-8"}
}
```

### Example Response

```json
{
  "id": 123,
  "user_id": 456,
  "exercise_type": "breathing",
  "goal_code": "focus_better",
  "soundscape_id": 12,
  "planned_duration_seconds": 1500,
  "planned_duration_minutes": 25.0,
  "start_at": "2025-09-25T10:00:00Z",
  "status": "in_progress",
  "tags": [],
  "metadata": {"breath_pattern": "4-7-8"},
  "created_at": "2025-09-25T10:00:00Z"
}
```

### Backend Table: `mindfulness_sessions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL PRIMARY KEY` | Auto-generated. |
| `user_id` | `INTEGER FK auth_users` | Cascade delete. |
| `exercise_type` | `TEXT` | Validated against whitelist. |
| `goal_code` | `TEXT FK mindfulness_goals(code)` | Nullable. |
| `soundscape_id` | `BIGINT FK mindfulness_soundscapes(id)` | Nullable. |
| `planned_duration_seconds` | `INT` | Computed from minutes. |
| `start_at` | `TIMESTAMPTZ` | Default now(). |
| `end_at` | `TIMESTAMPTZ` | Set on completion. |
| `actual_duration_seconds` | `INT` | Computed on completion. |
| `cycles_completed` | `INT` | User-reported. |
| `rating_relaxation` | `SMALLINT` | 1-10. |
| `rating_stress_before/after` | `SMALLINT` | 1-10. |
| `rating_mood_before/after` | `SMALLINT` | 1-10. |
| `score_restful` | `NUMERIC(5,2)` | Derived 0-100. |
| `score_focus` | `NUMERIC(5,2)` | Derived 0-100. |
| `tags` | `TEXT[]` | Free tagging. |
| `metadata` | `JSONB` | Breath pattern, device, etc. |
| `created_at` | `TIMESTAMPTZ` | Default now(). |

### When to call it

- **Start session flow:** After user selects goal, duration, and soundscape, post to create the session before transitioning to the live session screen.

---

## GET `/mindful/sessions`

### What it does

Retrieves a paginated list of the user's mindfulness sessions, optionally filtered by exercise type, goal, or date range.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `limit` | int | 20 | 1-100. |
| `offset` | int | 0 | For pagination. |
| `exercise_type` | string | null | Filter by type. |
| `goal_code` | string | null | Filter by goal. |
| `range` | string | null | e.g., "30d", "90d". |

### Example Request

```
GET /mindful/sessions?limit=10&exercise_type=breathing&range=30d
Authorization: Bearer <token>
```

### Example Response

```json
{
  "items": [
    {
      "id": 123,
      "exercise_type": "breathing",
      "goal_code": "focus_better",
      "planned_duration_minutes": 25.0,
      "actual_minutes": 24.5,
      "start_at": "2025-09-25T10:00:00Z",
      "end_at": "2025-09-25T10:24:30Z",
      "status": "completed",
      "score_restful": 85.5,
      "score_focus": 78.2,
      "tags": ["morning"],
      "metadata": {}
    }
  ],
  "next_offset": 10
}
```

### When to call it

- **History screen:** Load on mount, with pagination for infinite scroll. Apply filters based on user selections.

---

## GET `/mindful/sessions/{session_id}`

### What it does

Fetches detailed information for a specific session by ID.

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `session_id` | int | Session ID. |

### Example Request

```
GET /mindful/sessions/123
Authorization: Bearer <token>
```

### Example Response

```json
{
  "id": 123,
  "exercise_type": "breathing",
  "goal_code": "focus_better",
  "planned_duration_minutes": 25.0,
  "actual_minutes": 24.5,
  "start_at": "2025-09-25T10:00:00Z",
  "end_at": "2025-09-25T10:24:30Z",
  "status": "completed",
  "rating_relaxation": 8,
  "rating_stress_before": 6,
  "rating_stress_after": 3,
  "rating_mood_before": 4,
  "rating_mood_after": 7,
  "score_restful": 85.5,
  "score_focus": 78.2,
  "tags": ["morning"],
  "metadata": {"notes": "Felt calmer"}
}
```

### When to call it

- **Session detail view:** When user taps on a session from history list.

---

## PATCH `/mindful/sessions/{session_id}/progress`

### What it does

Updates mid-session progress like cycles completed or elapsed time. Only works if session is not completed.

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `session_id` | int | Session ID. |

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `cycles_completed` | int | No | >=0. |
| `elapsed_seconds` | int | No | >=0. |
| `metadata` | object | No | Merges into existing. |

### Example Request

```
PATCH /mindful/sessions/123/progress
Authorization: Bearer <token>
Content-Type: application/json

{
  "cycles_completed": 10,
  "elapsed_seconds": 600
}
```

### Example Response

```json
{
  "status": "ok",
  "session": {
    "id": 123,
    "cycles_completed": 10,
    "actual_duration_seconds": 600,
    "status": "in_progress"
  }
}
```

### When to call it

- **Live session timer:** Periodically update progress as the session runs.

---

## PATCH `/mindful/sessions/{session_id}/complete`

### What it does

Marks the session as completed, computes scores, and stores ratings.

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `session_id` | int | Session ID. |

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `cycles_completed` | int | No | >=0. |
| `rating_relaxation` | int | No | 1-10. |
| `rating_stress_before` | int | No | 1-10. |
| `rating_stress_after` | int | No | 1-10. |
| `rating_mood_before` | int | No | 1-10. |
| `rating_mood_after` | int | No | 1-10. |
| `metadata` | object | No | Merges into existing. |

### Example Request

```
PATCH /mindful/sessions/123/complete
Authorization: Bearer <token>
Content-Type: application/json

{
  "cycles_completed": 40,
  "rating_relaxation": 8,
  "rating_stress_before": 6,
  "rating_stress_after": 3,
  "rating_mood_before": 4,
  "rating_mood_after": 7
}
```

### Example Response

```json
{
  "id": 123,
  "end_at": "2025-09-25T10:24:30Z",
  "actual_duration_seconds": 1470,
  "actual_minutes": 24.5,
  "score_restful": 85.5,
  "score_focus": 78.2,
  "status": "completed"
}
```

### When to call it

- **Completion screen:** When user finishes the session and submits ratings.

---

## GET `/mindful/sessions/{session_id}/events`

### What it does

Lists granular events for a session, like breath phases.

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `session_id` | int | Session ID. |

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `limit` | int | 200 | 1-1000. |

### Example Request

```
GET /mindful/sessions/123/events?limit=50
Authorization: Bearer <token>
```

### Example Response

```json
{
  "items": [
    {
      "id": 456,
      "event_type": "breath_in",
      "numeric_value": 4.0,
      "occurred_at": "2025-09-25T10:01:00Z",
      "metadata": {}
    }
  ]
}
```

### Backend Table: `mindfulness_session_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL PRIMARY KEY` | Auto-generated. |
| `session_id` | `BIGINT FK mindfulness_sessions(id)` | Cascade delete. |
| `user_id` | `INTEGER FK auth_users(id)` | Cascade delete. |
| `event_type` | `TEXT` | e.g., "phase_start", "breath_in". |
| `numeric_value` | `NUMERIC` | Optional value. |
| `text_value` | `TEXT` | Optional text. |
| `occurred_at` | `TIMESTAMPTZ` | Default now(). |
| `metadata` | `JSONB` | Arbitrary. |
| `created_at` | `TIMESTAMPTZ` | Default now(). |

### When to call it

- **Session replay/analytics:** For detailed breakdowns in advanced views.

---

## POST `/mindful/sessions/{session_id}/events`

### What it does

Appends a new event to the session timeline.

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `session_id` | int | Session ID. |

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `event_type` | string | Yes | Min length 1. |
| `numeric_value` | float | No |  |
| `text_value` | string | No |  |
| `occurred_at` | datetime | No | Defaults to now. |
| `metadata` | object | No |  |

### Example Request

```
POST /mindful/sessions/123/events
Authorization: Bearer <token>
Content-Type: application/json

{
  "event_type": "pause",
  "numeric_value": 30.0,
  "text_value": "User paused"
}
```

### Example Response

```json
{
  "id": 789,
  "session_id": 123,
  "event_type": "pause",
  "numeric_value": 30.0,
  "text_value": "User paused",
  "occurred_at": "2025-09-25T10:05:00Z",
  "metadata": {},
  "created_at": "2025-09-25T10:05:00Z"
}
```

### When to call it

- **Live session tracking:** Log events as they happen during the exercise.

---

## GET `/mindful/stats/overview`

### What it does

Provides aggregated stats like total minutes, streaks, and breakdowns by exercise type.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `range` | string | "30d" | e.g., "7d", "30d", "90d", "1y". |

### Example Request

```
GET /mindful/stats/overview?range=30d
Authorization: Bearer <token>
```

### Example Response

```json
{
  "range": "30d",
  "total_minutes": 491.5,
  "total_hours": 8.19,
  "by_exercise_type": [
    {"exercise_type": "breathing", "minutes": 120.0, "sessions": 6}
  ],
  "streak_days": 5,
  "sessions_count": 14,
  "avg_session_minutes": 35.1,
  "last_session": {
    "id": 345,
    "exercise_type": "breathing",
    "end_at": "2025-09-25T10:24:30Z",
    "minutes": 24.9,
    "score_restful": 82.5
  }
}
```

### When to call it

- **Dashboard/stats screen:** Load on mount to show summary metrics.

---

## GET `/mindful/stats/daily`

### What it does

Returns daily aggregated mindful minutes, optionally filtered by exercise type.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `days` | int | 30 | 1-180. |
| `exercise_type` | string | null | Filter by type. |

### Example Request

```
GET /mindful/stats/daily?days=30&exercise_type=breathing
Authorization: Bearer <token>
```

### Example Response

```json
{
  "items": [
    {"day": "2025-09-01", "minutes": 35.0, "exercise_type": "breathing"}
  ]
}
```

### When to call it

- **Charts/graphs:** For time-series visualizations in stats views.

---

## GET `/mindful/sessions/active`

### What it does

Retrieves the currently active (in-progress) session for the user, if any.

### Example Request

```
GET /mindful/sessions/active
Authorization: Bearer <token>
```

### Example Response

```json
{
  "session": {
    "id": 123,
    "exercise_type": "breathing",
    "start_at": "2025-09-25T10:00:00Z",
    "status": "in_progress"
  }
}
```

Or `{"session": null}` if none.

### When to call it

- **App launch/resume:** Check if there's an ongoing session to resume.
