from pydantic import BaseModel

from app.agent.state import AgentState
from app.core.budget import BudgetExceededError, check_budget
from app.core.config import settings
from app.services.llm import call_gemini_structured

BLOCKED_DOMAINS = {
    "linkedin.com",
    "crunchbase.com",
    "g2.com",
    "capterra.com",
    "clutch.co",
    "glassdoor.com",
    "indeed.com",
    "wellfound.com",
    "ycombinator.com",
    "pitchbook.com",
    "zoominfo.com",
    "apollo.io",
}


class PrefilterResult(BaseModel):
    kept_domains: list[str]


def _extract_domain(lead: object) -> str:
    raw = lead.domain if hasattr(lead, "domain") else (lead.get("domain", "") if isinstance(lead, dict) else "")
    return str(raw or "").lower().strip().removeprefix("www.")


def _dedupe_and_clean(raw_leads: list) -> list:
    seen: set[str] = set()
    cleaned: list = []
    for lead in raw_leads:
        domain = _extract_domain(lead)
        if not domain or "." not in domain:
            continue
        if any(domain == b or domain.endswith("." + b) for b in BLOCKED_DOMAINS):
            continue
        if domain in seen:
            continue
        seen.add(domain)
        cleaned.append(lead)
    return cleaned


def prefilter_node(state: AgentState) -> dict:
    raw_leads = state.get("raw_leads", [])
    max_leads = max(1, int(state.get("max_leads") or 5))
    spent = float(state.get("budget_spent_usd") or 0.0)
    cap = float(getattr(settings, "max_run_budget_usd", 1.0) or 1.0)

    cleaned_leads = _dedupe_and_clean(raw_leads)
    if not cleaned_leads:
        return {"prefiltered_leads": [], "budget_spent_usd": round(min(cap, spent), 6)}

    if settings.mock_mode or len(cleaned_leads) <= 1:
        return {
            "prefiltered_leads": cleaned_leads[:max_leads],
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    try:
        check_budget(spent, estimated_next_cost=0.001)
    except BudgetExceededError:
        return {
            "prefiltered_leads": cleaned_leads[:max_leads],
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    icp_plan = state.get("icp_plan")
    leads_payload = [
        lead.model_dump() if hasattr(lead, "model_dump") else lead
        for lead in cleaned_leads
    ]

    fast_model = getattr(settings, "gemini_fast_model", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
    prompt = (
        f"You are a B2B lead pre-filter.\n"
        f"ICP Plan: {icp_plan}\n"
        f"Candidate Leads: {leads_payload}\n\n"
        f"Return the domains of up to {max_leads} real company leads that best match the ICP."
    )

    result, cost_usd = call_gemini_structured(
        prompt=prompt,
        response_schema=PrefilterResult,
        model=fast_model,
    )

    kept_set = {d.lower().strip().removeprefix("www.") for d in result.kept_domains}
    filtered = [
        lead for lead in cleaned_leads
        if _extract_domain(lead) in kept_set
    ][:max_leads]

    # Fallback if model returned empty list on valid cleaned leads
    if not filtered:
        filtered = cleaned_leads[:max_leads]

    updated_spent = round(min(cap, spent + float(cost_usd or 0.0)), 6)
    return {
        "prefiltered_leads": filtered,
        "budget_spent_usd": updated_spent,
    }