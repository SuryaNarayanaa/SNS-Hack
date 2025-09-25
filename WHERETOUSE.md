Public / Core
GET / Purpose: Simple welcome payload to verify the service is alive. Auth: None. Frontend use: Rare—use /health instead for uptime pings.

GET /health Purpose: Lightweight readiness probe (status ok). Auth: None. Frontend use: Health check for monitoring or a “service online” badge before showing login.

GET /diagram Purpose: Returns Mermaid source of the LangGraph agent graph. Auth: None (could expose internal structure). Frontend use: Developer / internal admin UI only, not end user.

POST /auth/register Purpose: Create a persistent user (email + password). Body: { email, password } Response: { access_token, expires_at, user{ id,email,is_guest,created_at } } Auth: None (pre-auth). Frontend use: Registration form submit. On success store access_token (secure storage) then redirect to app shell.

POST /auth/login Purpose: Authenticate existing user; issues new session token. Body: { email, password } Response: Same shape as register. Frontend use: Login form submit. Also use to refresh token by re-entering credentials if you have no refresh endpoint yet.

POST /auth/guest Purpose: Creates a temporary guest user with shorter session TTL. Body: { display_name? } Response: Same auth envelope (is_guest = true). Frontend use: “Continue as guest” button. Warn user about limited persistence.

POST /chat Purpose: Starts an SSE stream with model response for a single user turn. Body: { message, user_context? } Response: text/event-stream (chunks + final [DONE]). Auth: Bearer required. Frontend use: Chat composer submission:

Immediately render user message locally.
Open SSE stream; append agent tokens as they arrive.
Optionally disable send button until stream completes.
Telemetry (Raw Behavioral Logging)
POST /telemetry/start_conversation Purpose: Creates a conversation row for grouping subsequent turns/events. Body: { title?, metadata? } Response: { conversation_id } Auth: Bearer. Frontend use: Call once when a new chat tab/session opens, store conversation_id in state.

POST /telemetry/event Purpose: Log a point-in-time behavioral signal (mood, stress, coping_action, crisis_flag, memory_write, etc.). Body: { event_type, numeric_value?, text_value?, tags?, metadata?, occurred_at?, conversation_id? } Response: { status: "ok" } Auth: Bearer. Frontend use: UI widgets (mood slider, stress scale, “I did breathing” button). Send immediately; don’t batch unless offline.

POST /telemetry/message Purpose: Log a single conversation turn (user or agent) with optional analysis fields. Body: { role, content?, intent?, sentiment?, coping_action?, response_latency_ms?, metadata?, conversation_id?, session_token? } Response: { status: "ok" } Auth: Bearer. Frontend use: You should log USER turns right after send (if server doesn’t auto-log). Agent turns can be logged server-side; only send from frontend if you enrich client-side (e.g., local sentiment). Include conversation_id to increment message count.

PATCH /telemetry/conversation/{conversation_id}/end Purpose: Marks conversation end time (idempotent). Body: none. Response: { status: "ended", conversation_id } Auth: Bearer. Frontend use: On tab close, explicit “End session”, or inactivity timeout. Fire-and-forget.

GET /telemetry/behavioral_events Purpose: Retrieve recent raw events (unaggregated). Query: ?limit=50 (default). Response: { items: [ { id,event_type,numeric_value,text_value,tags,metadata,occurred_at } ] } Auth: Bearer. Frontend use: Personal dashboard “Recent mood & actions” list or QA panel. Avoid aggressive polling—cache or refresh on view focus.

GET /telemetry/conversation_messages Purpose: Recent logged conversation turns with light annotations. Query: ?limit=50. Response: { items: [ { id,role,intent,sentiment,coping_action,conversation_id,occurred_at } ] } Auth: Bearer. Frontend use: Analytics side panel (intent distribution preview) or to reconstruct recent context for a summary view.

Analytics (Aggregated Views)
GET /analytics/daily-scores Purpose: Daily averages of numeric *rating events (e.g., mood_rating, stress_rating). Query: days (1–180, default 30). Response: { items: [ { day, event_type, avg_score, samples } ] } Auth: Bearer. Frontend use: Trend charts (line / area). Cache; refresh on timeframe change.

GET /analytics/daily-crisis Purpose: Daily counts of crisis_flag events. Query: days (1–365, default 30). Response: { items: [ { day, crisis_events } ] } Auth: Bearer. Frontend use: Risk monitoring sparkline / alert dashboard.

GET /analytics/daily-intents Purpose: Daily counts of message intents (from conversation_behavior). Query: days (1–120, default 14). Response: { items: [ { day, intent, intent_messages } ] } Auth: Bearer. Frontend use: Stacked bar / heatmap for therapy technique usage or user engagement taxonomy.

GET /analytics/conversations/recent Purpose: Recent conversations with duration and message_count. Query: limit (1–100, default 20). Response: { items: [ { id,start_at,end_at,message_count,duration_seconds,metadata } ] } Auth: Bearer. Frontend use: Session history list, drill-down selector. Use to populate a “resume last session” tile.

Suggested Frontend Integration Order
Auth: /auth/register or /auth/login → store token.
Conversation start: /telemetry/start_conversation → save conversation_id.
Chat turn: POST /chat (stream); immediately POST /telemetry/message (role=user).
Agent logging: Either server-side (preferred) or POST /telemetry/message (role=agent).
Behavioral inputs: POST /telemetry/event for mood/stress/coping.
Session end: PATCH /telemetry/conversation/{id}/end on exit.
Dashboards: GET analytics + telemetry lists on demand (no constant polling).
When NOT to Call from Frontend
Don’t call /telemetry/message for agent turns if backend already instruments subagents.
Don’t expose /diagram to end users.
Avoid calling analytics endpoints for every page render; debounce or cache.
Minimal Payload Cheatsheet
User message log: { role: "user", content: "...", conversation_id } Mood rating: { event_type: "mood_rating", numeric_value: 6.5, conversation_id } Coping action: { event_type: "coping_action", text_value: "deep_breathing", conversation_id }