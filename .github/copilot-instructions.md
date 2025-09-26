# SNS Hack · Copilot Working Notes

1. **Environment first.** The runtime expects Python ≥3.13 (see `pyproject.toml`) plus the packages pinned in `req.txt`. Install them with `pip install -r req.txt`. Load a `.env` file or export `GOOGLE_API_KEY` before importing `agent.root_agent`; it raises immediately if the key is missing. Optionally set `GOOGLE_MODEL_NAME` (defaults to `gemini-2.0-flash`).
2. **Primary entry point.** `agent/root_agent.py` builds a LangGraph `StateGraph` called `supervisor`. Use `agent.invoke_supervisor(message, user_context=...)` to drive conversations, or run `python -m agent.root_agent` for the sample prompt at the bottom of that file.
3. **State contract.** Every node receives a `MessagesState` dict containing:
   - `messages`: list of LangChain `BaseMessage` objects.
   - `user_context`: optional string (fallbacks to `utils.DEFAULT_USER_CONTEXT`).
   - Extra keys may be attached via `extra_state`.
   Preserve this structure when extending the graph; mutate state by returning `{"messages": updated_list}` as shown in each sub-agent.
4. **Supervision + handoffs.** `create_handoff_tool` wraps `Command` routing to child nodes. Each tool name follows `transfer_to_<agent>` and must be registered in the `tools` list passed to `create_react_agent`. When adding a new specialist node, mirror the existing pattern: define the callable, register it with `.add_node`, and wire an edge back to `supervisor` for continued routing.
5. **Sub-agent pattern.** Files in `agent/subagents/` (CBT/DBT/ACT/fallback/memory/ant detection) all:
   - Load a prompt template from `agent/prompts.py` via `ChatPromptTemplate.from_template`.
   - Pull contextual strings with helpers in `agent/utils.py` to avoid manual message parsing.
   - Invoke `ChatGoogleGenerativeAI` synchronously and append the response to the shared `messages` list.
   Replicate this structure for any new modality to keep consistency.
6. **Conversation utilities.** `agent/utils.py` provides canonical formatting. Prefer `get_conversation_history` (optionally skipping the most recent user turn), `get_recent_conversation_history` (default window `RECENT_HISTORY_WINDOW = 6`), and `_coerce_content_to_text` for structured tool outputs. Reuse these helpers instead of re-serializing messages manually.
7. **Memory semantics.** The `memory_module` node expects both full and sliding-window histories and is the only component calling `get_full_conversation_history`. If you modify conversation retention, update this module alongside any new memory consumers.
8. **Prompts as single source.** Therapeutic tone and guidance live in `agent/prompts.py`. Adjusting a modality’s behavior should happen here first; agent code assumes each template supplies `{user_context}`, `{conversation_history}`, and `{user_message}` placeholders (memory module adds `{full_conversation_history}` / `{recent_conversation_history}`).
9. **Tooling gaps.** `agent/RAG.py` is currently empty—if you introduce retrieval workflows, define them there and import from the relevant nodes. Keep separation between retrieval utilities and conversational logic.
10. **Testing + linting.** No automated tests or linters are configured. When adding functionality, include a minimal reproducible driver (e.g., update `main.py` or add a script) and document any new run commands in `README.md` so future agents can exercise the graph quickly.
