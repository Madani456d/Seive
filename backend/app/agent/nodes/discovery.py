from typing import Any

from app.agent.state import AgentState
from app.core.config import settings
from app.services.treg_client import CostTracker, TregClient


def _build_queries(state: AgentState) -> list[str]:
    plan = state.get("icp_plan")
    queries: list[str] = []

    if isinstance(plan, dict):
        raw_queries = plan.get("search_queries") or plan.get("queries") or []
        if isinstance(raw_queries, list):
            queries.extend(str(q).strip() for q in raw_queries if str(q).strip())
    elif plan is not None:
        attr_queries = getattr(plan, "search_queries", None) or []
        queries.extend(str(q).strip() for q in attr_queries if str(q).strip())

    user_query = str(state.get("user_query") or "").strip()
    if user_query and user_query not in queries:
        queries.append(user_query)

    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:3]


async def discovery_node(state: AgentState) -> dict[str, Any]:
    current_spent = float(state.get("budget_spent_usd") or 0.0)
    max_leads = max(1, min(25, int(state.get("max_leads") or 5)))

    tracker = CostTracker(max_budget_usd=settings.max_run_budget_usd)
    tracker.spent_usd = current_spent

    queries = _build_queries(state)
    if not queries:
        return {
            "raw_leads": [],
            "budget_spent_usd": tracker.spent_usd,
        }

    client = TregClient()
    discovered = await client.discover_leads(
        queries=queries,
        limit=max_leads,
        budget=tracker,
    )

    return {
        "raw_leads": discovered,
        "budget_spent_usd": tracker.spent_usd,
    }