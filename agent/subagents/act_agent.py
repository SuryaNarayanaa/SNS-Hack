from langchain_core.messages import AIMessage

def act_agent(state):
    response = "This is a dummy ACT Agent. It handles Acceptance and Commitment Therapy tasks."
    return {"messages": state["messages"] + [AIMessage(content=response)]}