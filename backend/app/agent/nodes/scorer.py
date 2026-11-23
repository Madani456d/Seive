from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.core.budget import BudgetExceededError, check_budget
from app.core.config import settings
from app.services.llm import call_gemini_structured


class ScoredLeadItem(BaseModel):
    company_name: str
    domain: str
    email: str | None = None
    score: int = Field(..., ge=0, le=100)
    angle: str


class ScoringResult(BaseModel):
    leads: list[ScoredLeadItem]


def _fallback_scored_leads(enriched_leads: list[dict], icp_plan: object, score: int = 60) -> list[dict]:
    icp_summary = getattr(icp_plan, "summary", None) or (
        icp_plan.get("summary") if isinstance(icp_plan, dict) else str(icp_plan or "target ICP")
    )
    return [
        {
            "company_name": lead.get("company_name", "Unknown"),
            "domain": lead.get("domain", ""),
            "email": lead.get("email"),
            "score": score,
            "angle": f"Tailor outreach to {lead.get('company_name', 'their team')} based on {icp_summary}.",
        }
        for lead in enriched_leads
    ]


def scorer_node(state: AgentState) -> dict:
    enriched_leads = state.get("enriched_leads", [])
    spent = float(state.get("budget_spent_usd") or 0.0)
    cap = float(getattr(settings, "max_run_budget_usd", 1.0) or 1.0)

    if not enriched_leads:
        return {"scored_leads": [], "budget_spent_usd": round(min(cap, spent), 6)}

    if settings.mock_mode:
        return {
            "scored_leads": _fallback_scored_leads(enriched_leads, state.get("icp_plan"), score=88),
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    estimated_next_cost = 0.002
    try:
        check_budget(spent, estimated_next_cost)
    except BudgetExceededError:
        return {
            "scored_leads": _fallback_scored_leads(enriched_leads, state.get("icp_plan"), score=55),
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    icp_plan = state.get("icp_plan")
    fast_model = getattr(settings, "gemini_fast_model", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
    prompt = (
        f"Score each enriched lead from 0 to 100 against the ICP plan and write a 1-sentence outreach angle.\n"
        f"ICP Plan: {icp_plan}\n"
        f"Enriched Leads: {enriched_leads}"
    )

    result, cost_usd = call_gemini_structured(
        prompt=prompt,
        response_schema=ScoringResult,
        model=fast_model,
    )

    updated_spent = round(min(cap, spent + float(cost_usd or 0.0)), 6)
    return {
        "scored_leads": [item.model_dump() for item in result.leads],
        "budget_spent_usd": updated_spent,
    }