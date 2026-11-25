import asyncio
import re
import time
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


def _parse_items(items: list[dict[str, Any]], text_key: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url", "")
        match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if not match:
            continue
        domain = match.group(1).lower().removeprefix("www.")
        raw_title = (item.get("title") or domain).split("-")[0].split("|")[0].strip()
        parsed.append(
            {
                "company_name": raw_title[:100],
                "domain": domain,
                "source_url": url,
                "description": (item.get(text_key) or "")[:350],
            }
        )
    return parsed


def _dedupe_leads(batches: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    for batch in batches:
        for item in batch:
            domain = item["domain"]
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            leads.append(item)
            if len(leads) >= limit:
                return leads
    return leads


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

        async with httpx.AsyncClient(timeout=5.0) as client:
            async def fetch_one(q: str) -> list[dict[str, Any]]:
                resp = await client.post(
                    f"{self.base_url}/call/exa.search",
                    headers=headers,
                    json={
                        "query": f"{q} official company site",
                        "numResults": max(limit + 2, 6),
                        "contents": {"text": {"maxCharacters": 250}},
                    },
                )
                resp.raise_for_status()
                return _parse_items(resp.json().get("results", []), "text")

            results = await asyncio.gather(*(fetch_one(q) for q in queries), return_exceptions=True)

        valid_batches = [r for r in results if isinstance(r, list)]
        return _dedupe_leads(valid_batches, limit)

    async def _discover_via_tavily(self, queries: list[str], limit: int) -> list[dict[str, Any]]:
        if not settings.tavily_api_key:
            return []

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.tavily_api_key}",
        }

        async with httpx.AsyncClient(timeout=6.0) as client:
            async def fetch_one(q: str) -> list[dict[str, Any]]:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    headers=headers,
                    json={
                        "query": f"{q} official company site",
                        "max_results": max(limit + 2, 6),
                        "search_depth": "basic",
                        "include_raw_content": False,
                    },
                )
                if resp.status_code in (429, 432, 433):
                    return []
                resp.raise_for_status()
                return _parse_items(resp.json().get("results", []), "content")

            results = await asyncio.gather(*(fetch_one(q) for q in queries), return_exceptions=True)

        valid_batches = [r for r in results if isinstance(r, list)]
        return _dedupe_leads(valid_batches, limit)

    async def discover_leads(
        self, queries: list[str], limit: int = 5, budget: CostTracker | None = None
    ) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        clean_queries = [q.strip() for q in (queries or []) if q and q.strip()][:2]
        if not clean_queries:
            return []

        candidate_cap = max(limit * 2, 6)
        candidates: list[dict[str, Any]] = []

        # Primary provider: Treg catalog call (concurrent)
        if self.api_key and (budget is None or budget.can_spend(0.02)):
            try:
                candidates = await self._discover_via_treg(clean_queries, candidate_cap)
                if budget and candidates:
                    budget.record(0.02)
            except Exception as exc:
                print(f"[discovery] Treg search fallback: {exc}", flush=True)
                candidates = []

        # Fallback provider: Live Tavily search (concurrent)
        if not candidates and settings.tavily_api_key and (budget is None or budget.can_spend(0.008)):
            try:
                candidates = await self._discover_via_tavily(clean_queries, candidate_cap)
                if budget and candidates:
                    budget.record(0.008)
            except Exception as exc:
                print(f"[discovery] Tavily search failed: {exc}", flush=True)
                candidates = []

        print(f"[discovery] Found {len(candidates)} candidates in {time.perf_counter() - t0:.2f}s", flush=True)
        return candidates