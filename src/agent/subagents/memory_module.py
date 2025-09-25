from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agent.prompts import MEMORY_MODULE_PROMPT
from agent.utils import (
    get_full_conversation_history,
    get_last_user_message,
    get_recent_conversation_history,
    get_user_context,
)
from db import insert_behavioral_event, insert_conversation_message


_prompt = ChatPromptTemplate.from_template(MEMORY_MODULE_PROMPT)
_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")


async def memory_module(state):
    messages = state.get("messages", [])
    formatted_messages = _prompt.format_messages(
        user_context=get_user_context(state),
        full_conversation_history=get_full_conversation_history(messages),
        recent_conversation_history=get_recent_conversation_history(messages),
        user_message=get_last_user_message(messages),
    )
    ai_message = await _llm.ainvoke(formatted_messages)
    # Fire-and-forget logging
    try:
        auth_user = state.get("extra_state", {}).get("auth_user") or {}
        user_id = auth_user.get("id")
        session_token = state.get("extra_state", {}).get("auth_user", {}).get("token")
        import asyncio
        asyncio.create_task(
            insert_behavioral_event(
                user_id,
                "memory_write",
                text_value="memory_module_output",
                metadata={"agent": "memory_module"},
                session_token=session_token,
            )
        )
        asyncio.create_task(
            insert_conversation_message(
                user_id,
                role="agent",
                content=ai_message.content,
                metadata={"agent": "memory_module"},
                session_token=session_token,
            )
        )
    except Exception:
        pass
    return {"messages": messages + [ai_message]}