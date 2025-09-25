from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agent.prompts import MEMORY_MODULE_PROMPT
from agent.utils import (
    get_full_conversation_history,
    get_last_user_message,
    get_recent_conversation_history,
    get_user_context,
)


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
    return {"messages": messages + [ai_message]}