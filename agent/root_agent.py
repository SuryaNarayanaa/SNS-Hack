from __future__ import annotations

import os
from typing import Annotated, Any, Mapping, MutableMapping, cast
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import MessagesState, START, StateGraph
from langgraph.prebuilt import InjectedState, create_react_agent
from langgraph.types import Command
from dotenv import load_dotenv
load_dotenv()

from agent.subagents.act_agent import act_agent
from agent.subagents.ant_detection_sub_agent import ant_detection_sub_agent
from agent.subagents.cbt_agent import cbt_agent
from agent.subagents.crisis_managment_agent import crisis_management_agent
from agent.subagents.dbt_agent import dbt_agent
from agent.subagents.fallback_agent import fallback_agent
from agent.subagents.memory_module import memory_module

os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GLOG_minloglevel'] = '2'


load_dotenv()
def create_handoff_tool(*, agent_name: str, description: str | None = None):
    name = f"transfer_to_{agent_name}"
    description = description or f"Ask {agent_name} for help."

    @tool(name, description=description)
    def handoff_tool(
        state: Annotated[MessagesState, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        tool_message = {
            "role": "tool",
            "content": f"Successfully transferred to {agent_name}",
            "name": name,
            "tool_call_id": tool_call_id,
        }
        return Command(
            goto=agent_name,  
            update={**state, "messages": state["messages"] + [tool_message]},  
            graph=Command.PARENT,  
        )

    return handoff_tool

# Handoffs
assign_to_cbt_agent = create_handoff_tool(
    agent_name="cbt_agent",
    description="Assign tasks related to Cognitive Behavioral Therapy to this agent.",
)

assign_to_dbt_agent = create_handoff_tool(
    agent_name="dbt_agent",
    description="Assign tasks related to Dialectical Behavior Therapy to this agent.",
)

assign_to_act_agent = create_handoff_tool(
    agent_name="act_agent",
    description="Assign tasks related to Acceptance and Commitment Therapy to this agent.",
)

assign_to_fallback_agent = create_handoff_tool(
    agent_name="fallback_agent",
    description="Assign general or unspecified tasks to this agent.",
)

assign_to_memory_module = create_handoff_tool(
    agent_name="memory_module",
    description="Assign memory-related operations to this agent.",
)

assign_to_ant_detection_sub_agent = create_handoff_tool(
    agent_name="ant_detection_sub_agent",
    description="Assign tasks for detecting Automatic Negative Thoughts to this agent.",
)

assign_to_crisis_management_agent = create_handoff_tool(
    agent_name="crisis_management_agent",
    description="URGENT: Assign immediately for crisis intervention, suicide risk, self-harm, or safety concerns.",
)

router_llm = ChatGoogleGenerativeAI(model='gemini-1.5-flash')


# Create supervisor agent
supervisor_agent = create_react_agent(
    model=router_llm,
    tools=[assign_to_crisis_management_agent, assign_to_cbt_agent, assign_to_dbt_agent, assign_to_act_agent, assign_to_fallback_agent, assign_to_memory_module, assign_to_ant_detection_sub_agent],
    prompt=(
        "You are a Master Router (Intent Classifier) managing several agents:\n"
        "- **CRISIS MANAGEMENT Agent**: **IMMEDIATELY** assign for ANY suicide risk, self-harm, hopelessness, or safety concerns\n"
        "- CBT Agent: Assign tasks related to Cognitive Behavioral Therapy\n"
        "- DBT Agent: Assign tasks related to Dialectical Behavior Therapy\n"
        "- ACT Agent: Assign tasks related to Acceptance and Commitment Therapy\n"
        "- Fallback Agent: Assign general or unspecified tasks\n"
        "- Memory Module: Assign memory-related operations\n"
        "- ANT Detection Sub-Agent: Assign tasks for detecting Automatic Negative Thoughts\n\n"
        "**CRITICAL PRIORITY: If you detect ANY crisis indicators (suicide, self-harm, 'want to die', 'can't go on', etc.), IMMEDIATELY transfer to crisis_management_agent**\n\n"
        "Classify the user's intent and delegate to the appropriate agent. Assign work to one agent at a time, do not call agents in parallel.\n"
        "Do not do any work yourself."
    ),
    name="supervisor",
)

# Define the multi-agent supervisor graph
supervisor = (
    StateGraph(MessagesState)
    # NOTE: destinations is only needed for visualization and doesn't affect runtime behavior
    .add_node(supervisor_agent, destinations=("crisis_management_agent", "cbt_agent", "dbt_agent", "act_agent", "fallback_agent", "memory_module", "ant_detection_sub_agent"))
    .add_node(crisis_management_agent)
    .add_node(cbt_agent)
    .add_node(dbt_agent)
    .add_node(act_agent)
    .add_node(fallback_agent)
    .add_node(memory_module)
    .add_node(ant_detection_sub_agent)
    .add_edge(START, "supervisor")

    .add_edge("crisis_management_agent", "supervisor")
    .add_edge("cbt_agent", "supervisor")
    .add_edge("dbt_agent", "supervisor")
    .add_edge("act_agent", "supervisor")
    .add_edge("fallback_agent", "supervisor")
    .add_edge("memory_module", "supervisor")
    .add_edge("ant_detection_sub_agent", "supervisor")
    .compile()
)


# result = supervisor.invoke({"messages": [HumanMessage(content="I have been feeling very anxious lately and it's affecting my daily life. Can you help me?")]})

# print(result)