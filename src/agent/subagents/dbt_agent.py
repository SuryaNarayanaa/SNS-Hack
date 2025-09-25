from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agent.prompts import DBT_AGENT_PROMPT
from agent.utils import (
    get_conversation_history,
    get_last_user_message,
    get_user_context,
)


_prompt = ChatPromptTemplate.from_template(DBT_AGENT_PROMPT)
_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash")


async def dbt_agent(state):
    messages = state.get("messages", [])
    formatted_messages = _prompt.format_messages(
        user_context=get_user_context(state),
        conversation_history=get_conversation_history(messages),
        user_message=get_last_user_message(messages),
    )
    ai_message = await _llm.ainvoke(formatted_messages)
    return {"messages": messages + [ai_message]}