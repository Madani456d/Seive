from app.agent.state import AgentState
from app.core.budget import BudgetExceededError, check_budget
from app.core.config import settings
from app.services.cache import get_cached_lead  # keep your existing import path if different
from app.services.treg import enrich_company_waterfall


async def waterfall_node(state: AgentState) -> dict:
    spent = float(state.get("budget_spent_usd") or 0.0)
    cap = float(getattr(settings, "max_run_budget_usd", 1.0) or 1.0)

    if not state.get("hitl_approved", False):
        return {
            "enriched_leads": [],
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    approved_leads = state.get("approved_leads", [])
    enriched_leads = []

    for lead in approved_leads:
        lead_dict = lead.model_dump() if hasattr(lead, "model_dump") else dict(lead)
        domain = str(lead_dict.get("domain") or "").lower().strip()
        if not domain:
            continue

        if settings.mock_mode or settings.mock_treg:
            enriched_leads.append({
                **lead_dict,
                "email": f"founder@{domain}",
                "enrichment_source": "mock",
            })
            continue

        cached = await get_cached_lead(domain)
        if cached:
            enriched_leads.append({
                **lead_dict,
                **cached,
                "enrichment_source": "cache",
            })
            continue

        # Guard budget per lead before making a paid enrichment call
        try:
            check_budget(spent, estimated_next_cost=0.02)
        except BudgetExceededError:
            enriched_leads.append({
                **lead_dict,
                "enrichment_source": "budget_capped",
            })
            continue

        treg_data, cost_usd = await enrich_company_waterfall(domain)
        spent = round(min(cap, spent + float(cost_usd or 0.0)), 6)

        enriched_leads.append({
            **lead_dict,
            **(treg_data or {}),
            "enrichment_source": "treg" if treg_data else "not_found",
        })

    return {
        "enriched_leads": enriched_leads,
        "budget_spent_usd": round(min(cap, spent), 6),
    }