from app.agent.state import AgentState
from app.core.budget import check_budget
from app.core.config import settings
from app.services.cache import get_cached_lead  # keep your existing import path if different
from app.services.treg import enrich_company_waterfall


async def waterfall_node(state: AgentState) -> dict:
    if not state.get("hitl_approved", False):
        return {"enriched_leads": []}

    approved_leads = state.get("approved_leads", [])
    spent = state.get("budget_spent_usd", 0.0)
    enriched_leads = []

    for lead in approved_leads:
        lead_dict = lead.model_dump() if hasattr(lead, "model_dump") else dict(lead)
        domain = lead_dict["domain"]

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

        # Guard budget before making a paid Treg call
        check_budget(spent, estimated_next_cost=0.02)
        treg_data, cost_usd = await enrich_company_waterfall(domain)
        spent = round(spent + cost_usd, 6)

        enriched_leads.append({
            **lead_dict,
            **(treg_data or {}),
            "enrichment_source": "treg" if treg_data else "not_found",
        })

    return {
        "enriched_leads": enriched_leads,
        "budget_spent_usd": spent,
    }
