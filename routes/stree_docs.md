# Stress Management API Reference

This document mirrors the structure of `goals_and_soundscapes.md` and describes every `/stress/*` route implemented in `stress_routes.py`. It covers authentication, request/response contracts, and recommended frontend integration touchpoints.

## Authentication

All stress management endpoints require a valid Bearer token. Every request must send:

```
Authorization: Bearer <session_token>
Content-Type: application/json
```

Requests without the header (or with an expired token) receive `401 Unauthorized` with an empty body. The APIs are namespaced under `/stress`.

---

## Endpoint Summary

| Endpoint | Method | Purpose | Typical UI Touchpoint |
|----------|--------|---------|------------------------|
| `/stress/stressors/catalog` | `GET` | Fetch selectable stressor categories | Stress self-report picker & insight filters |
| `/stress/assessment` | `POST` | Submit a stress check-in | Daily self-report flow (score + stressors) |
| `/stress/assessments` | `GET` | Paginated list of assessments with filters | History screen, analytics feeds |
| `/stress/assessments/recent` | `GET` | Most recent N assessments | Dashboard sparkline & mini feed |
| `/stress/assessments/{id}` | `GET` | Detailed assessment record | Assessment detail modal/screen |
| `/stress/summary/overview` | `GET` | Current level, trend, top stressors, distribution | Stress card on home dashboard |
| `/stress/stats/daily` | `GET` | Daily averages over a range | Trend charts, calendar view |
| `/stress/stats/stressors` | `GET` | Aggregated stats per stressor | Bubble chart / top stressors list |
| `/stress/expression/start` | `POST` | Begin an optional expression/biometrics session | Camera/sensor capture overlay |
| `/stress/expression/{id}/metrics` | `PATCH` | Append biometric metrics (single or batch) | Background metrics sync from device |
| `/stress/expression/{id}/complete` | `PATCH` | Mark expression session complete, compute aggregates | Capture completion CTA (user confirms or timeout) |
| `/stress/expression/{id}` | `GET` | Fetch expression session details (optionally metrics) | Session review, QA tooling |
| `/stress/insights` | `GET` | List trend/anomaly insights | Insights tab, notifications center |
| `/stress/insights/{id}` | `PATCH` | Update insight status | Insight acknowledgment/dismissal flows |

---

## GET `/stress/stressors/catalog`

### What it does

Returns the selectable stressor catalog. Each stressor is a reusable label used when submitting assessments and surfacing insights.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `active` | boolean | `true` | `true` for active only, `false` for archived, omit to retrieve all. |

### Example Request

```
GET /stress/stressors/catalog?active=true
Authorization: Bearer <token>
```

```powershell
curl -H "Authorization: Bearer $env:TOKEN" `
     "https://api.example.com/stress/stressors/catalog?active=true"
```

### Example Response

```json
{
  "items": [
    {
      "id": 1,
      "slug": "work",
      "name": "Work",
      "description": "Workload or workplace related stress",
      "is_active": true,
      "metadata": {"icon": "briefcase", "color": "#FF9E57"}
    }
  ]
}
```

### Backend Table: `stress_stressors`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL PRIMARY KEY` | |
| `slug` | `TEXT UNIQUE NOT NULL` | Used in assessment payloads. |
| `name` | `TEXT NOT NULL` | Display label. |
| `description` | `TEXT` | Optional copy for tooltips. |
| `is_active` | `BOOLEAN DEFAULT TRUE` | Hide archived items. |
| `metadata` | `JSONB` | Icon/color hints. |
| `created_at` | `TIMESTAMPTZ` | Auto-managed timestamp. |

### When to call it

- **Assessment form:** Populate the stressor multi-select when a user submits a new check-in.
- **Insights filters:** Provide stressor filter chips in insights screen.
- **Cache strategy:** Catalog changes rarely; refresh on app launch or manual refresh.

---

## POST `/stress/assessment`

### What it does

Creates a new stress assessment with a numeric score (0–5) and optional context. Also links selected stressors and an expression session if provided.

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `score` | int | Yes | 0–5 scale (maps to qualitative label). |
| `stressor_slugs` | array[string] | No | Each slug must exist in `stress_stressors`. Deduplicated server-side. |
| `context_note` | string | No | Up to ~2K chars of free text. |
| `expression_session_id` | int | No | Must refer to the user’s open session. |
| `metadata` | object | No | Extra attributes (e.g., `{"time_of_day":"evening"}`). |

### Example Request

```
POST /stress/assessment
Authorization: Bearer <token>
Content-Type: application/json

{
  "score": 3,
  "stressor_slugs": ["work", "loneliness"],
  "context_note": "After a long remote work day",
  "metadata": {"time_of_day": "evening"}
}
```

### Example Response

```json
{
  "id": 1201,
  "score": 3,
  "qualitative_label": "elevated",
  "context_note": "After a long remote work day",
  "expression_session_id": null,
  "metadata": {"time_of_day": "evening"},
  "created_at": "2025-09-25T21:15:00Z",
  "stressors": [
    {"id": 1, "slug": "work", "impact_level": null, "impact_score": null},
    {"id": 2, "slug": "loneliness", "impact_level": null, "impact_score": null}
  ]
}
```

### Backend Tables Touched

- `stress_assessments`
- `stress_assessment_stressors`
- `stress_expression_sessions` (metadata update when linked)

### When to call it

- **Daily check-in flow:** After user selects score and stressors.
- **Automated triggers:** Optionally from wearable/assistant flows when a user logs stress verbally.

---

## GET `/stress/assessments`

### What it does

Retrieves a paginated list of assessments for the user with optional filters on date range, scores, or containing stressor slug.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `limit` | int | `30` | 1–100. |
| `offset` | int | `0` | For pagination / infinite scroll. |
| `from` | ISO datetime | `null` | Inclusive lower bound on `created_at`. |
| `to` | ISO datetime | `null` | Inclusive upper bound. |
| `min_score` | int | `null` | 0–5. |
| `max_score` | int | `null` | 0–5. |
| `stressor` | string | `null` | Filter assessments containing the slug. |

### Example Request

```
GET /stress/assessments?limit=20&from=2025-09-01T00:00:00Z&stressor=work
Authorization: Bearer <token>
```

### Example Response

```json
{
  "items": [
    {
      "id": 1201,
      "score": 3,
      "qualitative_label": "elevated",
      "context_note": "Long remote work day",
      "created_at": "2025-09-25T21:15:00Z"
    }
  ],
  "next_offset": 20
}
```

### When to call it

- **History tab:** Populate the chronological list with infinite scroll.
- **Analytics export:** Provide filter controls (date range, score range, stressor).

---

## GET `/stress/assessments/recent`

### What it does

Returns the most recent N assessments (descending order). Lightweight endpoint for dashboards and sparklines.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `limit` | int | `10` | 1–50 maximum. |

### Example Response

```json
{
  "items": [
    {
      "id": 1204,
      "score": 4,
      "qualitative_label": "high",
      "context_note": null,
      "created_at": "2025-09-26T06:45:00Z"
    }
  ]
}
```

### When to call it

- **Home dashboard sparkline:** Fetch on mount and refresh periodically.
- **Notifications panel:** Show latest entries when nudging user about streaks.

---

## GET `/stress/assessments/{assessment_id}`

### What it does

Retrieves a single assessment with linked stressors and expression session summary (if available).

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `assessment_id` | int | Assessment identifier. |

### Example Response

```json
{
  "id": 1201,
  "score": 3,
  "qualitative_label": "elevated",
  "context_note": "After a long remote work day",
  "expression_session_id": 55,
  "metadata": {"time_of_day": "evening"},
  "created_at": "2025-09-25T21:15:00Z",
  "stressors": [
    {"id": 1, "slug": "work", "name": "Work", "impact_level": "moderate", "impact_score": 0.52},
    {"id": 2, "slug": "loneliness", "name": "Loneliness", "impact_level": "low", "impact_score": 0.31}
  ],
  "expression_session": {
    "id": 55,
    "started_at": "2025-09-25T21:00:00Z",
    "completed_at": "2025-09-25T21:05:00Z",
    "status": "completed",
    "metadata": {"session_stats": {"samples": 42, "avg_hr": 67.4}}
  }
}
```

### When to call it

- **Detailed view:** When user taps an assessment in history.
- **Clinician review:** For per-assessment drill downs in admin tools.

---

## GET `/stress/summary/overview`

### What it does

Provides a single dashboard payload containing the current (latest) stress reading, trend information, top stressors, and distribution counts over a requested window.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `range` | string | `30d` | Supports `7d`, `14d`, `30d`, `90d`, or custom like `60d`. |

### Example Response

```json
{
  "current": {
    "score": 3,
    "qualitative_label": "elevated",
    "created_at": "2025-09-25T21:15:00Z"
  },
  "trend": {
    "direction": "up",
    "slope": 0.12,
    "delta_vs_prev_period": 0.4
  },
  "top_stressors": [
    {"slug": "loneliness", "name": "Loneliness", "avg_score": 3.8, "avg_impact_score": 0.72, "impact_level": "very_high"},
    {"slug": "work", "name": "Work", "avg_score": 2.9, "avg_impact_score": 0.48, "impact_level": "high"}
  ],
  "distribution": {
    "calm": 5,
    "normal": 12,
    "elevated": 8,
    "high": 3,
    "extreme": 1
  }
}
```

### When to call it

- **Dashboard stress card:** On initial load and when user changes time range.
- **Weekly digest:** Use to craft summary notifications/email digests.

---

## GET `/stress/stats/daily`

### What it does

Returns aggregated average scores and assessment counts per day for a given window. Uses the `stress_daily_stats` continuous aggregate when available.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `days` | int | `30` | Range 1–180 days. |

### Example Response

```json
{
  "items": [
    {
      "day": "2025-09-20",
      "avg_score": 2.6,
      "assessments": 3
    },
    {
      "day": "2025-09-21",
      "avg_score": 3.1,
      "assessments": 2
    }
  ]
}
```

### When to call it

- **Trend charts:** Plot daily averages in line or bar charts.
- **Calendar heat map:** Map `avg_score` to color intensity.

---

## GET `/stress/stats/stressors`

### What it does

Provides aggregated statistics per stressor over the requested window (assessment count, average score, average impact score).

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `days` | int | `30` | Range 1–180 days. |
| `limit` | int | `10` | Maximum number of stressors to return (1–50). |

### Example Response

```json
{
  "items": [
    {
      "slug": "loneliness",
      "name": "Loneliness",
      "assessments": 14,
      "avg_score": 3.8,
      "avg_impact_score": 0.72
    },
    {
      "slug": "work",
      "name": "Work",
      "assessments": 9,
      "avg_score": 2.9,
      "avg_impact_score": 0.55
    }
  ]
}
```

### When to call it

- **Top stressor bubbles:** Size/color nodes by average impact.
- **Coaching recommendations:** Prioritize stress management tips based on dominant stressors.

---

## POST `/stress/expression/start`

### What it does

Creates a new expression session for optional biometric/video capture tied to a stress check-in.

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `capture_type` | string | No | E.g., `camera`, `sensor`, `combined`. Defaults to `camera`. |
| `metadata` | object | No | Arbitrary context (e.g. lighting conditions). |
| `device_capabilities` | object | No | Hardware details such as resolution or available sensors. |

### Example Response

```json
{
  "id": 55,
  "user_id": 42,
  "started_at": "2025-09-25T21:00:00Z",
  "completed_at": null,
  "capture_type": "camera",
  "status": "in_progress",
  "metadata": null,
  "device_capabilities": {"resolution": "720p"}
}
```

### When to call it

- **Capture onboarding:** Before showing the live recording component.
- **Retry logic:** Create a fresh session if the prior one was aborted.

---

## PATCH `/stress/expression/{session_id}/metrics`

### What it does

Appends biometric metrics to an expression session. Accepts either a single metrics object or a batch (`{"items": [...]}`) to reduce network overhead.

### Path Parameters

| Name | Type | Notes |
|------|------|-------|
| `session_id` | int | Target expression session. |

### Request Body (single item)

| Field | Type | Notes |
|-------|------|-------|
| `captured_at` | datetime | Defaults to current time if omitted. |
| `heart_rate_bpm` | float | Optional. |
| `systolic_bp` | int | Optional. |
| `diastolic_bp` | int | Optional. |
| `breathing_rate` | float | Optional. |
| `expression_primary` | string | Optional label (e.g., `neutral`). |
| `expression_confidence` | float | 0–1. |
| `stress_inference` | float | Model output 0–100. |
| `metadata` | object | Optional raw metrics / quality flags. |

### Example Request (batch)

```
PATCH /stress/expression/55/metrics
Authorization: Bearer <token>
Content-Type: application/json

{
  "items": [
    {"heart_rate_bpm": 68, "stress_inference": 47.2},
    {"heart_rate_bpm": 70, "stress_inference": 45.1, "captured_at": "2025-09-25T21:02:00Z"}
  ]
}
```

### Example Response

```json
{ "status": "ok", "accepted": 2 }
```

### When to call it

- **Background ingestion:** Stream metrics during capture.
- **Wearable sync:** Send batches after offline collection.

---

## PATCH `/stress/expression/{session_id}/complete`

### What it does

Marks an expression session as completed, calculates aggregates (average/peak heart rate, average stress inference), and merges additional metadata.

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `metadata` | object | No | Include quality summaries or device notes. |

### Example Response

```json
{
  "id": 55,
  "user_id": 42,
  "started_at": "2025-09-25T21:00:00Z",
  "completed_at": "2025-09-25T21:05:00Z",
  "capture_type": "camera",
  "status": "completed",
  "metadata": {"session_stats": {"avg_hr": 67.4, "avg_stress": 45.1, "samples": 42}},
  "samples": 42,
  "avg_heart_rate": 67.4,
  "avg_stress_inference": 45.1,
  "peak_heart_rate": 80.2
}
```

### When to call it

- **Capture completion dialog:** After user confirms the session finished successfully.
- **Auto-timeout:** When the system detects inactivity beyond the threshold.

---

## GET `/stress/expression/{session_id}`

### What it does

Retrieves an expression session along with summary stats. Optionally returns paginated raw metrics.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `include_metrics` | boolean | `false` | When `true`, returns metrics array. |
| `metrics_limit` | int | `100` | Max metrics per page (1–500). |
| `metrics_offset` | int | `0` | Offset for paging metrics. |

### Example Response (include_metrics=true)

```json
{
  "id": 55,
  "user_id": 42,
  "started_at": "2025-09-25T21:00:00Z",
  "completed_at": "2025-09-25T21:05:00Z",
  "capture_type": "camera",
  "status": "completed",
  "metadata": {"session_stats": {"avg_hr": 67.4}},
  "device_capabilities": {"resolution": "720p"},
  "samples": 42,
  "avg_heart_rate": 67.4,
  "avg_stress_inference": 45.1,
  "peak_heart_rate": 80.2,
  "metrics": [
    {"captured_at": "2025-09-25T21:00:10Z", "heart_rate_bpm": 68, "stress_inference": 47.2}
  ]
}
```

### When to call it

- **Review screen:** Let users review captured metrics before deletion.
- **QA tooling:** Investigate anomalous sessions by retrieving raw samples.

---

## GET `/stress/insights`

### What it does

Lists AI-generated stress insights (trends, spikes, anomalies). Supports filtering by status, insight type, and recent window.

### Query Parameters

| Name | Type | Default | Notes |
|------|------|---------|-------|
| `status` | array[string] | `null` | Filter statuses (e.g., `new`, `acknowledged`). |
| `type` | array[string] | `null` | Filter by insight type (e.g., `trend_increase`). |
| `days` | int | `null` | Only insights detected within last N days (1–365). |
| `limit` | int | `20` | 1–100. |
| `offset` | int | `0` | Pagination offset. |

### Example Response

```json
{
  "items": [
    {
      "id": 9,
      "insight_type": "trend_increase",
      "severity": "moderate",
      "title": "Stress trending up in evenings",
      "description": "Average evening score has increased by 0.4 over the last 14 days",
      "suggested_action": "Try a wind-down exercise before bed",
      "status": "new",
      "related_stressor_id": 2,
      "first_detected_at": "2025-09-15T19:00:00Z",
      "last_occurrence_at": "2025-09-25T21:00:00Z",
      "metadata": {"trend_slope": 0.12},
      "created_at": "2025-09-25T21:05:00Z",
      "updated_at": "2025-09-25T21:05:00Z"
    }
  ],
  "next_offset": null
}
```

### When to call it

- **Insights tab:** Populate cards when user visits the insights screen.
- **Notifications:** Pull fresh insights for push/email campaigns.

---

## PATCH `/stress/insights/{insight_id}`

### What it does

Updates the status of an insight (e.g., mark as acknowledged or dismissed). Returns the updated record.

### Request Body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `status` | string | Yes | Accepts statuses like `acknowledged`, `dismissed`, `resolved`. |

### Example Request

```
PATCH /stress/insights/9
Authorization: Bearer <token>
Content-Type: application/json

{ "status": "acknowledged" }
```

### Example Response

```json
{
  "id": 9,
  "insight_type": "trend_increase",
  "severity": "moderate",
  "title": "Stress trending up in evenings",
  "description": "Average evening score has increased by 0.4 over the last 14 days",
  "suggested_action": "Try a wind-down exercise before bed",
  "status": "acknowledged",
  "related_stressor_id": 2,
  "first_detected_at": "2025-09-15T19:00:00Z",
  "last_occurrence_at": "2025-09-25T21:00:00Z",
  "metadata": {"trend_slope": 0.12},
  "created_at": "2025-09-25T21:05:00Z",
  "updated_at": "2025-09-26T08:10:00Z"
}
```

### When to call it

- **Insight interaction:** When user marks an insight as acknowledged/dismissed.
- **Automation:** Sync statuses with downstream CRM/coaching tools.

---

## Frontend Integration Tips

- **Caching:** Catalog and insights data can be cached with SWR/React Query. Revalidate catalog sparingly; assessments/stats should use background refresh on focus.
- **Error Handling:** Handle `401` by re-authenticating. For `404` on PATCH routes, show a toast that the underlying resource no longer exists.
- **Joining Data:** Assessments reference stressor slugs; maintain lookup maps for local rendering. Insights may need to map `related_stressor_id` back to catalog results.
- **Accessibility:** Distributions and insights include descriptive fields—surface them via screen reader-friendly text.

Keep this document aligned with backend changes. Update sections if routes evolve or new fields are added.
