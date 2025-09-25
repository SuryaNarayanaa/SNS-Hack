from langchain_core.messages import AIMessage

def ant_detection_sub_agent(state):
    response = "This is a dummy ANT Detection Sub-Agent. It detects Automatic Negative Thoughts."
    return {"messages": state["messages"] + [AIMessage(content=response)]}