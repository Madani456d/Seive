from langgraph.graph import StateGraph, START, END
from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node
from app.agent.nodes.discovery import discovery_node
from app.agent.nodes.prefilter import prefilter_node
from app.agent.nodes.hitl_gate import hitl_gate_node
from app.agent.nodes.waterfall import waterfall_node
from app.agent.nodes.scorer import scorer_node


def route_after_hitl(state: AgentState) -> str:
    if state.get("hitl_approved") and state.get("approved_leads"):
        return "waterfall"
    return END


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("planner", planner_node)
    builder.add_node("discovery", discovery_node)
    builder.add_node("prefilter", prefilter_node)
    builder.add_node("hitl_gate", hitl_gate_node)
    builder.add_node("waterfall", waterfall_node)
    builder.add_node("scorer", scorer_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "discovery")
    builder.add_edge("discovery", "prefilter")
    builder.add_edge("prefilter", "hitl_gate")
    builder.add_conditional_edges(
        "hitl_gate",
        route_after_hitl,
        {"waterfall": "waterfall", END: END},
    )
    builder.add_edge("waterfall", "scorer")
    builder.add_edge("scorer", END)

    return builder.compile(checkpointer=checkpointer)
