from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.core.budget import check_budget
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


def scorer_node(state: AgentState) -> dict:
    enriched_leads = state.get("enriched_leads", [])
    spent = state.get("budget_spent_usd", 0.0)

    if not enriched_leads:
        return {"scored_leads": [], "budget_spent_usd": spent}

    if settings.mock_mode:
        mock_scored = [
            {
                "company_name": lead.get("company_name", "Unknown"),
                "domain": lead.get("domain", ""),
                "email": lead.get("email"),
                "score": 88,
                "angle": f"Highlight how you solve workflow bottlenecks for {lead.get('company_name', 'their team')}.",
            }
            for lead in enriched_leads
        ]
        return {
            "scored_leads": mock_scored,
            "budget_spent_usd": spent,
        }

    check_budget(spent)

    icp_plan = state.get("icp_plan")
    prompt = (
        f"Score each enriched lead from 0 to 100 against the ICP plan and write a 1-sentence outreach angle.\n"
        f"ICP Plan: {icp_plan}\n"
        f"Enriched Leads: {enriched_leads}"
    )

    result, cost_usd = call_gemini_structured(
        prompt=prompt,
        response_schema=ScoringResult,
        model="gemini-3.8-flash",
    )

    return {
        "scored_leads": [item.model_dump() for item in result.leads],
        "budget_spent_usd": round(spent + cost_usd, 6),
    }
