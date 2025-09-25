# SNS Hack Backend

This project exposes a FastAPI backend that routes conversations through a LangGraph supervisor coordinating several therapeutic sub-agents. The service now ships with basic user authentication (registered and guest accounts) backed by PostgreSQL/TimescaleDB via `asyncpg`.

## Prerequisites

- Python 3.13+
- A PostgreSQL-compatible database URL exported as `TIMESCALE_SERVICE_URL`
- Google Generative AI key exported as `GOOGLE_API_KEY`
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

## Running the API

```bash
python main.py
```

The server listens on `http://0.0.0.0:8000` by default (override with `PORT`).

## Running Tests

All automated tests use `pytest` with `pytest-asyncio` fixtures. After installing the dependencies listed above, run:

```bash
uv run pytest
```

If you prefer to invoke pytest directly, activate your virtual environment and run `pytest`. The suite exercises scoring logic, trigger heuristics, and database writes using the stubs in `tests/stubs.py`.

## Authentication Workflows

| Endpoint | Description |
| --- | --- |
| `POST /auth/register` | Create a new user with `username` and `password`. Returns a bearer token. |
| `POST /auth/login` | Exchange username/password for a bearer token. |
| `POST /auth/guest` | Provision a short-lived guest identity. Optional `display_name` overrides the generated username. |
| `POST /chat` | Protected route. Requires `Authorization: Bearer <token>` header. Streams responses as Server-Sent Events. |
| `GET /diagram` | Unprotected route returning a Mermaid diagram of the agent flow. |

Tokens expire automatically (12 hours for registered users, 4 hours for guests). Clients should refresh by re-authenticating.

## Database Schema

`db.py` seeds two tables during startup:
- `auth_users` – stores usernames, password hashes, guest flag, timestamps.
- `auth_sessions` – stores bearer tokens with expiry timestamps (expired rows are purged periodically).

## Chat Streaming

`POST /chat` expects a JSON body:
```json
{
  "message": "I feel overwhelmed",
  "user_context": "Preparing for a demo"
}
```
Responses arrive as SSE chunks (`text/event-stream`). Each `data:` line represents a fragment of the model output; a final `data: [DONE]` signals completion.

## Troubleshooting

- Double-check required environment variables before importing `agent.root_agent` or starting the server; missing keys raise immediately.
- Run `python -m compileall main.py agent/subagents/*.py auth.py db.py` to perform a quick syntax check.
