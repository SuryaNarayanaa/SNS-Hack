from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agent.prompts import ANT_DETECTION_PROMPT
from agent.utils import get_conversation_history, get_last_user_message


_prompt = ChatPromptTemplate.from_template(ANT_DETECTION_PROMPT)
_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")


async def ant_detection_sub_agent(state):
    messages = state.get("messages", [])
    formatted_messages = _prompt.format_messages(
        user_message=get_last_user_message(messages),
        conversation_context=get_conversation_history(messages, include_last_user=True),
    )
    ai_message = await _llm.ainvoke(formatted_messages)
    return {"messages": messages + [ai_message]}