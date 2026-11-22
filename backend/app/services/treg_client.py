import httpx
from app.core.config import settings


class TregClient:
    def __init__(self):
        self.mock_mode = settings.mock_mode or settings.mock_treg
        self.token = settings.treg_token or settings.treg_api_key
        self.base_url = settings.treg_base_url
        if not self.mock_mode and not self.token:
            raise ValueError(
                "TREG_TOKEN is required when MOCK_MODE=false and MOCK_TREG=false"
            )

    async def discover_leads(self, queries: list[str], limit: int = 5) -> list[dict]:
        if self.mock_mode:
            mock_leads = [
                {
                    "company_name": "DevFlow Labs",
                    "domain": "devflowlabs.io",
                    "description": "CI/CD observability platform for 15-50 person engineering teams.",
                    "location": "San Francisco, US",
                    "employees": 28,
                },
                {
                    "company_name": "ShipStack AI",
                    "domain": "shipstack.ai",
                    "description": "Automated code review and release pipelines for B2B SaaS startups.",
                    "location": "Austin, US",
                    "employees": 19,
                },
                {
                    "company_name": "TraceGrid",
                    "domain": "tracegrid.dev",
                    "description": "Lightweight distributed tracing for TypeScript and Python backends.",
                    "location": "New York, US",
                    "employees": 35,
                },
                {
                    "company_name": "QueryPulse",
                    "domain": "querypulse.com",
                    "description": "Real-time Postgres performance monitoring for growing SaaS apps.",
                    "location": "Seattle, US",
                    "employees": 22,
                },
                {
                    "company_name": "LocalBakery Co",
                    "domain": "localbakery.shop",
                    "description": "Artisanal neighborhood bakery and catering service.",
                    "location": "Chicago, US",
                    "employees": 12,
                },
            ]
            return mock_leads[:limit]

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        discovered = []

        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in queries:
                if len(discovered) >= limit:
                    break
                try:
                    resp = await client.post(
                        f"{self.base_url}/tools/company-search",
                        headers=headers,
                        json={"query": query, "limit": limit - len(discovered)},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        discovered.extend(data.get("results", []))
                except httpx.HTTPError:
                    continue

        return discovered[:limit]


treg_client = TregClient()