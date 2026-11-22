from pydantic import BaseModel

from app.agent.state import AgentState
from app.core.budget import check_budget
from app.core.config import settings
from app.services.llm import call_gemini_structured


class PrefilterResult(BaseModel):
    kept_domains: list[str]


def prefilter_node(state: AgentState) -> dict:
    raw_leads = state.get("raw_leads", [])
    max_leads = state.get("max_leads", 5)
    spent = state.get("budget_spent_usd", 0.0)

    if not raw_leads:
        return {"prefiltered_leads": [], "budget_spent_usd": spent}

    if settings.mock_mode:
        return {
            "prefiltered_leads": raw_leads[:max_leads],
            "budget_spent_usd": spent,
        }

    check_budget(spent)

    icp_plan = state.get("icp_plan")
    leads_payload = [
        lead.model_dump() if hasattr(lead, "model_dump") else lead
        for lead in raw_leads
    ]

    prompt = (
        f"You are a B2B lead pre-filter.\n"
        f"ICP Plan: {icp_plan}\n"
        f"Candidate Leads: {leads_payload}\n\n"
        f"Return the domains of up to {max_leads} leads that best match the ICP."
    )

    result, cost_usd = call_gemini_structured(
        prompt=prompt,
        response_schema=PrefilterResult,
        model="gemini-3.8-flash",
    )

    kept_set = {d.lower().strip() for d in result.kept_domains}
    filtered = [
        lead for lead in raw_leads
        if (lead.domain if hasattr(lead, "domain") else lead.get("domain", "")).lower().strip() in kept_set
    ][:max_leads]

    return {
        "prefiltered_leads": filtered,
        "budget_spent_usd": round(spent + cost_usd, 6),
    }
