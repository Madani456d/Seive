from app.agent.state import AgentState
from app.services.treg_client import treg_client


async def discovery_node(state: AgentState) -> dict:
    plan = state.get("icp_plan")
    queries = plan.search_queries if plan else [state["user_query"]]
    raw_leads = await treg_client.discover_leads(queries=queries, limit=5)
    return {"raw_leads": raw_leads}
