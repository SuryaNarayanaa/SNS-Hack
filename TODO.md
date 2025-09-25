# TODO — Additional API endpoints to add

Suggested endpoints to expand functionality based on the existing codebase. Each item links to relevant files / symbols to make implementation easier.

- Auth
  - `GET /auth/me` — return the current authenticated user. See [`get_user_by_token`](auth.py) and [`get_current_user`](main.py).
  - `POST /auth/logout` — revoke the current bearer token. Use [`auth.revoke_session`](auth.py).
  - `POST /auth/refresh` — rotate a session token (create new with [`create_session`](auth.py) and revoke old token via [`revoke_session`](auth.py)).
  - `GET /auth/sessions` — list active sessions for the current user (requires new DB query helpers in [`auth.py`], schema in [`db.py`]).

- User management
  - `GET /users/{id}` — fetch user profile (implement DB helper in [`auth.py`] / [`db.py`]).
  - `GET /users` — admin list of users (requires permission checks).

- Chat / Conversations
  - `POST /chat/feedback` — submit feedback for the last response (persist in DB or file).
  - `GET /chat/history` — return stored conversation history for a user (requires persisting conversation state).
  - `GET /chat/session/{session_id}` — replay an SSE stream or return full transcript.

- Agent control & diagnostics
  - `POST /agent/invoke` — direct, synchronous invocation of the supervisor (wrap [`agent.supervisor.invoke`]/[`agent.supervisor.astream_events`] from [`agent/root_agent.py`]).
  - `GET /diagram` — existing endpoint returns the mermaid graph (`/diagram` already implemented in [`main.py`]).

- Database / maintenance
  - `POST /db/init` — run [`init_db`](db.py) manually (useful for CI or first-run setup).
  - `POST /db/test` — run [`test_db_connection`](db.py) to validate connectivity.
  - `POST /admin/cleanup_sessions` — run [`cleanup_expired_sessions`](auth.py) on-demand.

- Observability & ops
  - `GET /metrics` — Prometheus metrics endpoint.
  - `GET /health` — already implemented in [`main.py`]; consider adding readiness/liveness variants.

- Retrieval / RAG & memory
  - `POST /rag/query` — add retrieval-augmented-generation using a new module (see empty RAG area in the notes: consider adding [`agent/RAG.py`] and wiring into [`agent/subagents/memory_module.py`]).
  - `GET /memory/{user_id}` — expose stored memory items (requires persisting memory).

- Admin / Safety
  - `POST /admin/flag` — manually flag conversations for clinical review (store audit in DB).
  - `GET /admin/flags` — list flagged conversations.

Implementation notes:
- Respect safety rules in [`agent/prompts.py`] and crisis handling in [`agent/subagents/crisis_managment_agent.py`] when exposing chat content.
- Persisting conversations and sessions requires schema changes and DB helpers in [`db.py`] / [`auth.py`].
- For streaming chat keep using SSE (`text/event-stream`) as implemented in [`main.py`].

References
- Main FastAPI entry: [main.py](main.py)
- Auth helpers: [auth.py](auth.py)
- DB utilities: [db.py](db.py)
- Agent graph / supervisor: [agent/root_agent.py](agent/root_agent.py)
- Agent prompts & subagents: [agent/prompts.py](agent/prompts.py), [agent/subagents](agent/subagents)




Examples (JSON bodies)

POST /telemetry/start_conversation { "title": "Evening check‑in", "metadata": { "context": "daily_reflection", "initial_mood_guess": "neutral" } }

POST /telemetry/event (mood rating) { "event_type": "mood_rating", "numeric_value": 6.5, "text_value": "slightly_better", "tags": ["evening","after_walk"], "metadata": { "scale": "0-10", "source": "self_report" }, "occurred_at": "2025-09-25T18:42:10Z", "conversation_id": 123 }

POST /telemetry/event (stress rating) { "event_type": "stress_rating", "numeric_value": 4.0, "text_value": "manageable", "tags": ["work"], "metadata": {"trigger": "email_backlog"} }

POST /telemetry/event (coping action) { "event_type": "coping_action", "text_value": "deep_breathing", "tags": ["breathing","grounding"], "metadata": {"duration_minutes": 5} }

POST /telemetry/event (crisis flag) { "event_type": "crisis_flag", "text_value": "moderate", "tags": ["hopelessness"], "metadata": { "risk_level": "moderate", "detected_by": "crisis_management_agent", "confidence": 0.82 }, "conversation_id": 123 }

POST /telemetry/event (memory write marker) { "event_type": "memory_write", "text_value": "stored_key_takeaway", "metadata": { "agent": "memory_module", "category": "value_statement" } }

POST /telemetry/message (user turn) { "role": "user", "content": "I felt anxious earlier but a short walk helped.", "intent": "anxiety_reflection", "sentiment": 0.15, "coping_action": null, "response_latency_ms": null, "metadata": { "extracted_entities": ["anxiety","walk"], "time_context": "evening" }, "conversation_id": 123 }

POST /telemetry/message (agent turn) { "role": "agent", "content": "Great job using a walk as a coping strategy. Want to note what specifically helped?", "intent": "reinforcement", "sentiment": 0.55, "coping_action": "reinforce_behavior", "response_latency_ms": 1200, "metadata": { "agent": "act_agent", "technique": "behavioral_activation" }, "conversation_id": 123 }

POST /telemetry/message (agent crisis response) { "role": "agent", "content": "Your safety matters. Here are immediate resources...", "intent": "crisis_intervention", "sentiment": -0.6, "metadata": { "agent": "crisis_management", "risk_level": "high" }, "conversation_id": 123 }

PATCH /telemetry/conversation/{conversation_id}/end (no body)

GET /telemetry/behavioral_events (query only: ?limit=50)

GET /telemetry/conversation_messages (query only: ?limit=50)

Notes

event_type expected set: mood_rating, stress_rating, anxiety_rating (if you add), coping_action, crisis_flag, intent_detected, memory_write, handoff.
numeric_value only for *_rating types.
occurred_at optional; omit for now-time.
conversation_id optional; include when tying to an active conversation.
Let me know if you want curl examples or a Postman collection.