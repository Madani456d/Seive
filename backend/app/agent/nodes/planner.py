import time
from app.agent.state import AgentState
from app.core.budget import check_budget
from app.core.config import settings
from app.schemas.lead import ICPPlan
from app.services.llm import call_gemini_structured


def planner_node(state: AgentState) -> dict:
    t0 = time.perf_counter()
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
    try:
        plan, cost_usd = call_gemini_structured(
            prompt=prompt,
            response_schema=ICPPlan,
            model=settings.gemini_planner_model,
        )
    except Exception as exc:
        print(f"[planner] Falling back to query-derived plan after error: {exc}", flush=True)
        plan = ICPPlan(
            target_industry=query[:80],
            company_size="10-200 employees",
            geography="Global",
            target_roles=["Founder", "CEO", "CTO"],
            search_keywords=[query],
        )
        cost_usd = 0.0

    print(f"[planner] Done in {time.perf_counter() - t0:.2f}s", flush=True)
    return {
        "icp_plan": plan,
        "budget_spent_usd": round(state.get("budget_spent_usd", 0.0) + cost_usd, 6),
    }