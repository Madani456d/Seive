import asyncio
import time

from app.agent.state import AgentState
from app.core.budget import BudgetExceededError, check_budget
from app.core.config import settings
from app.services.cache import get_cached_lead  # keep your existing import path if different
from app.services.treg import enrich_company_waterfall

ESTIMATED_COST_PER_LEAD = 0.02
MAX_CONCURRENT_ENRICHMENTS = 5
PER_LEAD_TIMEOUT_SEC = 12.0


async def waterfall_node(state: AgentState) -> dict:
    t0 = time.perf_counter()
    spent = float(state.get("budget_spent_usd") or 0.0)
    cap = float(getattr(settings, "max_run_budget_usd", 1.0) or 1.0)

    if not state.get("hitl_approved", False):
        return {
            "enriched_leads": [],
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    approved_leads = state.get("approved_leads", [])
    normalized: list[dict] = []
    for lead in approved_leads:
        lead_dict = lead.model_dump() if hasattr(lead, "model_dump") else dict(lead)
        domain = str(lead_dict.get("domain") or "").lower().strip()
        if domain:
            lead_dict["domain"] = domain
            normalized.append(lead_dict)

    if not normalized:
        return {
            "enriched_leads": [],
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    # Fast path for mock modes
    if settings.mock_mode or settings.mock_treg:
        return {
            "enriched_leads": [
                {**lead_dict, "email": f"founder@{lead_dict['domain']}", "enrichment_source": "mock"}
                for lead_dict in normalized
            ],
            "budget_spent_usd": round(min(cap, spent), 6),
        }

    # 1. Check cache concurrently for all approved leads first (free & fast)
    cached_results = await asyncio.gather(
        *(get_cached_lead(lead_dict["domain"]) for lead_dict in normalized),
        return_exceptions=True,
    )

    # 2. Reserve budget slots upfront for uncached leads so parallel calls stay within cap
    reserved_spent = spent
    sem = asyncio.Semaphore(MAX_CONCURRENT_ENRICHMENTS)

    async def _enrich_one(lead_dict: dict, cached: object) -> tuple[dict, float]:
        domain = lead_dict["domain"]

        if cached and not isinstance(cached, Exception):
            return ({**lead_dict, **cached, "enrichment_source": "cache"}, 0.0)

        nonlocal reserved_spent
        try:
            check_budget(reserved_spent, estimated_next_cost=ESTIMATED_COST_PER_LEAD)
            reserved_spent = round(reserved_spent + ESTIMATED_COST_PER_LEAD, 6)
        except BudgetExceededError:
            return ({**lead_dict, "enrichment_source": "budget_capped"}, 0.0)

        async with sem:
            try:
                treg_data, cost_usd = await asyncio.wait_for(
                    enrich_company_waterfall(domain),
                    timeout=PER_LEAD_TIMEOUT_SEC,
                )
                return (
                    {
                        **lead_dict,
                        **(treg_data or {}),
                        "enrichment_source": "treg" if treg_data else "not_found",
                    },
                    float(cost_usd or 0.0),
                )
            except asyncio.TimeoutError:
                print(f"[waterfall] Timeout enriching {domain} after {PER_LEAD_TIMEOUT_SEC}s", flush=True)
                return ({**lead_dict, "enrichment_source": "timeout"}, 0.0)
            except Exception as exc:
                print(f"[waterfall] Error enriching {domain}: {exc}", flush=True)
                return ({**lead_dict, "enrichment_source": "error"}, 0.0)

    results = await asyncio.gather(
        *(_enrich_one(lead_dict, cached) for lead_dict, cached in zip(normalized, cached_results))
    )

    enriched_leads = [item[0] for item in results]
    total_actual_cost = sum(item[1] for item in results)
    final_spent = round(min(cap, spent + total_actual_cost), 6)

    elapsed = time.perf_counter() - t0
    print(
        f"[waterfall] Enriched {len(enriched_leads)} leads concurrently in {elapsed:.2f}s (cost=${total_actual_cost:.4f})",
        flush=True,
    )

    return {
        "enriched_leads": enriched_leads,
        "budget_spent_usd": final_spent,
    }