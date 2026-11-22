import httpx
from app.core.config import settings


async def enrich_company_waterfall(domain: str) -> tuple[dict | None, float]:
    headers = {
        "Authorization": f"Bearer {settings.treg_token or settings.treg_api_key}",
        "Content-Type": "application/json",
    }

    providers = [
        {"tool": "company-enrich-primary", "est_cost": 0.01},
        {"tool": "company-enrich-fallback", "est_cost": 0.015},
    ]

    total_cost = 0.0

    async with httpx.AsyncClient(timeout=15.0) as client:
        for provider in providers:
            try:
                resp = await client.post(
                    f"{settings.treg_base_url}/tools/{provider['tool']}",
                    headers=headers,
                    json={"domain": domain},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    cost = float(data.get("cost_usd", provider["est_cost"]))
                    total_cost += cost
                    if data.get("email") or data.get("contacts"):
                        return data, round(total_cost, 6)
            except httpx.HTTPError:
                continue

    return None, round(total_cost, 6)
