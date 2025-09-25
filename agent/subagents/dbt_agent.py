from langchain_core.messages import AIMessage

def dbt_agent(state):
    response = "This is a dummy DBT Agent. It handles Dialectical Behavior Therapy tasks."
    return {"messages": state["messages"] + [AIMessage(content=response)]}