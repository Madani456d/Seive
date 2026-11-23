import re
from typing import Any
import httpx
from app.core.config import settings


class CostTracker:
    def __init__(self, max_budget_usd: float):
        self.max_budget_usd = float(max_budget_usd)
        self.spent_usd = 0.0

    def can_spend(self, estimated_usd: float) -> bool:
        return (self.spent_usd + float(estimated_usd)) <= self.max_budget_usd

    def record(self, amount_usd: float) -> None:
        self.spent_usd = round(min(self.max_budget_usd, self.spent_usd + float(amount_usd)), 6)


class TregClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        raw_base = (base_url or getattr(settings, "treg_base_url", "") or "https://treg.to").rstrip("/")
        self.base_url = "https://treg.to" if "api.treg.ai" in raw_base else raw_base
        self.api_key = (api_key or getattr(settings, "treg_api_key", "") or "").strip()

    async def _discover_via_treg(self, queries: list[str], limit: int) -> list[dict[str, Any]]:
        if not self.api_key or not self.base_url:
            return []

        headers = {
            "Content-Type": "application/json",
            "X-Treg-Token": self.api_key,
        }
        leads: list[dict[str, Any]] = []
        seen_domains: set[str] = set()

        async with httpx.AsyncClient(timeout=10.0) as client:
            for q in queries:
                if len(leads) >= limit:
                    break
                resp = await client.post(
                    f"{self.base_url}/call/exa.search",
                    headers=headers,
                    json={
                        "query": f"{q} official company site",
                        "numResults": max(limit + 3, 6),
                        "contents": {"text": {"maxCharacters": 350}},
                    },
                )
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    url = item.get("url", "")
                    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    if not match:
                        continue
                    domain = match.group(1).lower().removeprefix("www.")
                    if domain in seen_domains:
                        continue
                    seen_domains.add(domain)
                    raw_title = (item.get("title") or domain).split("-")[0].split("|")[0].strip()
                    leads.append(
                        {
                            "company_name": raw_title[:100],
                            "domain": domain,
                            "source_url": url,
                            "description": (item.get("text") or "")[:350],
                        }
                    )
                    if len(leads) >= limit:
                        break
        return leads

    async def _discover_via_tavily(self, queries: list[str], limit: int) -> list[dict[str, Any]]:
        if not settings.tavily_api_key:
            return []

        leads: list[dict[str, Any]] = []
        seen_domains: set[str] = set()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.tavily_api_key}",
        }

        async with httpx.AsyncClient(timeout=12.0) as client:
            for q in queries:
                if len(leads) >= limit:
                    break
                resp = await client.post(
                    "https://api.tavily.com/search",
                    headers=headers,
                    json={
                        "query": f"{q} official company site",
                        "max_results": max(limit + 3, 6),
                        "search_depth": "basic",
                        "include_raw_content": False,
                    },
                )
                if resp.status_code in (429, 432, 433):
                    break
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    url = item.get("url", "")
                    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    if not match:
                        continue
                    domain = match.group(1).lower().removeprefix("www.")
                    if domain in seen_domains:
                        continue
                    seen_domains.add(domain)
                    raw_title = (item.get("title") or domain).split("-")[0].split("|")[0].strip()
                    leads.append(
                        {
                            "company_name": raw_title[:100],
                            "domain": domain,
                            "source_url": url,
                            "description": (item.get("content") or "")[:350],
                        }
                    )
                    if len(leads) >= limit:
                        break
        return leads

    async def discover_leads(
        self, queries: list[str], limit: int = 5, budget: CostTracker | None = None
    ) -> list[dict[str, Any]]:
        clean_queries = [q.strip() for q in (queries or []) if q and q.strip()]
        if not clean_queries:
            return []

        candidate_cap = max(limit * 2, 6)
        candidates: list[dict[str, Any]] = []

        # Primary provider: Treg catalog call
        if self.api_key and (budget is None or budget.can_spend(0.02)):
            try:
                candidates = await self._discover_via_treg(clean_queries, candidate_cap)
                if budget and candidates:
                    budget.record(0.02)
            except Exception:
                candidates = []

        # Fallback provider: Live Tavily search for real company pages
        if not candidates and settings.tavily_api_key and (budget is None or budget.can_spend(0.008)):
            try:
                candidates = await self._discover_via_tavily(clean_queries, candidate_cap)
                if budget and candidates:
                    budget.record(0.008)
            except Exception:
                candidates = []

        return candidates[:candidate_cap]