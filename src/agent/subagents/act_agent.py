from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agent.prompts import ACT_AGENT_PROMPT
from agent.utils import (
    get_conversation_history,
    get_last_user_message,
    get_user_context,
)
from db import insert_conversation_message


_prompt = ChatPromptTemplate.from_template(ACT_AGENT_PROMPT)
_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")


async def act_agent(state):
    messages = state.get("messages", [])
    formatted_messages = _prompt.format_messages(
        user_context=get_user_context(state),
        conversation_history=get_conversation_history(messages),
        user_message=get_last_user_message(messages),
    )
    ai_message = await _llm.ainvoke(formatted_messages)
    try:
        auth_user = state.get("extra_state", {}).get("auth_user") or {}
        user_id = auth_user.get("id")
        session_token = state.get("extra_state", {}).get("auth_user", {}).get("token")
        import asyncio
        asyncio.create_task(
            insert_conversation_message(
                user_id,
                role="agent",
                content=ai_message.content,
                intent="act_therapy",
                metadata={"agent": "act_agent"},
                session_token=session_token,
            )
        )
    except Exception:
        pass
    return {"messages": messages + [ai_message]}