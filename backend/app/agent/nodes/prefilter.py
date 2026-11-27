import time
from urllib.parse import urlparse
from pydantic import BaseModel

from app.agent.state import AgentState
from app.core.budget import BudgetExceededError, check_budget
from app.core.config import settings
from app.services.llm import call_gemini_structured

BLOCKED_DOMAINS = {
    "linkedin.com",
    "crunchbase.com",
    "tracxn.com",
    "g2.com",
    "capterra.com",
    "clutch.co",
    "glassdoor.com",
    "indeed.com",
    "foundit.in",
    "founditgulf.com",
    "naukri.com",
    "monster.com",
    "wellfound.com",
    "ycombinator.com",
    "pitchbook.com",
    "dealroom.co",
    "zoominfo.com",
    "apollo.io",
    "forbes.com",
    "techcrunch.com",
    "bloomberg.com",
    "fintechweekly.com",
    "wikipedia.org",
}


class PrefilterResult(BaseModel):
    kept_domains: list[str]


def _extract_domain(lead: object) -> str:
    raw = (
        lead.domain
        if hasattr(lead, "domain")
        else (lead.get("domain", "") if isinstance(lead, dict) else "")
    )
    val = str(raw or "").lower().strip()
    if "://" in val:
        val = urlparse(val).netloc
    return val.removeprefix("www.").split("/")[0]


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


def _compact_lead(lead: object) -> dict:
    item = (
        lead.model_dump()
        if hasattr(lead, "model_dump")
        else (dict(lead) if isinstance(lead, dict) else {})
    )
    snippet = str(
        item.get("snippet") or item.get("description") or item.get("summary") or ""
    )
    return {
        "domain": _extract_domain(lead),
        "company_name": str(item.get("company_name") or item.get("name") or "")[:80],
        "snippet": snippet[:160],
    }


def prefilter_node(state: AgentState) -> dict:
    t0 = time.perf_counter()
    raw_leads = state.get("raw_leads", [])
    max_leads = max(1, int(state.get("max_leads") or 5))
    spent = float(state.get("budget_spent_usd") or 0.0)
    cap = float(getattr(settings, "max_run_budget_usd", 1.0) or 1.0)

    cleaned_leads = _dedupe_and_clean(raw_leads)
    if not cleaned_leads:
        return {"prefiltered_leads": [], "budget_spent_usd": round(min(cap, spent), 6)}

    # Fast path (0 ms): skip LLM call when deterministic cleaning already fits within max_leads
    if settings.mock_mode or len(cleaned_leads) <= max_leads:
        elapsed = time.perf_counter() - t0
        print(
            f"[prefilter] Fast-kept {len(cleaned_leads[:max_leads])} leads in {elapsed:.4f}s",
            flush=True,
        )
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
    compact_payload = [_compact_lead(lead) for lead in cleaned_leads]

    fast_model = (
        getattr(settings, "gemini_fast_model", "gemini-3.1-flash-lite")
        or "gemini-3.1-flash-lite"
    )
    prompt = (
        f"Select up to {max_leads} real target company domains matching this ICP "
        f"(exclude recruiters, news sites, directories, and unrelated orgs).\n"
        f"ICP: {icp_plan}\n"
        f"Candidates: {compact_payload}"
    )

    try:
        result, cost_usd = call_gemini_structured(
            prompt=prompt,
            response_schema=PrefilterResult,
            model=fast_model,
        )
        kept_set = {
            d.lower().strip().removeprefix("www.") for d in result.kept_domains
        }
        filtered = [
            lead for lead in cleaned_leads if _extract_domain(lead) in kept_set
        ][:max_leads]
    except Exception as exc:
        print(f"[prefilter] Fallback after error: {exc}", flush=True)
        filtered = []
        cost_usd = 0.0

    if not filtered:
        filtered = cleaned_leads[:max_leads]

    updated_spent = round(min(cap, spent + float(cost_usd or 0.0)), 6)
    elapsed = time.perf_counter() - t0
    print(
        f"[prefilter] Filtered {len(raw_leads)} -> {len(filtered)} in {elapsed:.2f}s",
        flush=True,
    )
    return {
        "prefiltered_leads": filtered,
        "budget_spent_usd": updated_spent,
    }