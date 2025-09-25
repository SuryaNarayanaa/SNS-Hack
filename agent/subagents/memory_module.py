from langchain_core.messages import AIMessage

def memory_module(state):
    response = "This is a dummy Memory Module. It handles memory-related operations."
    return {"messages": state["messages"] + [AIMessage(content=response)]}