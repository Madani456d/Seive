from app.agent.state import AgentState
from app.core.budget import check_budget
from app.core.config import settings
from app.schemas.lead import ICPPlan
from app.services.llm import call_gemini_structured


def planner_node(state: AgentState) -> dict:
    query = state["user_query"]

    if settings.mock_mode:
        plan = ICPPlan(
            target_industry="B2B SaaS / Developer Tools",
            company_size="10-50 employees",
            geography="United States",
            target_roles=["CTO", "VP of Engineering", "Founder"],
            search_keywords=["devtools", "b2b saas", "developer platform"],
        )
        return {
            "icp_plan": plan,
            "budget_spent_usd": state.get("budget_spent_usd", 0.0),
        }

    check_budget(state.get("budget_spent_usd", 0.0))

    prompt = (
        f"Convert this lead generation request into a structured ICP plan.\n"
        f"User request: {query}"
    )
    plan, cost_usd = call_gemini_structured(
        prompt=prompt,
        response_schema=ICPPlan,
        model="gemini-2.5-flash-lite",
    )

    return {
        "icp_plan": plan,
        "budget_spent_usd": round(state.get("budget_spent_usd", 0.0) + cost_usd, 6),
    }
