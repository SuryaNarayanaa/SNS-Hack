from langchain_core.messages import AIMessage

def cbt_agent(state):
    response = "This is a dummy CBT Agent. It handles Cognitive Behavioral Therapy tasks."
    return {"messages": state["messages"] + [AIMessage(content=response)]}