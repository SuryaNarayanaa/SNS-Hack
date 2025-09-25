Use from frontend

POST /telemetry/start_conversation once when a new chat session begins (store conversation_id).
POST /telemetry/message for each user message (role="user", content, conversation_id).
POST /telemetry/event for explicit user inputs (mood slider, stress rating, coping action selections).
PATCH /telemetry/conversation/{id}/end when the user leaves or session ends.