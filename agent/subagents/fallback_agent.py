from langchain_core.messages import AIMessage

def fallback_agent(state):
    response = "This is a dummy Fallback Agent. It handles general or unspecified tasks."
    return {"messages": state["messages"] + [AIMessage(content=response)]}