import re
import httpx
from app.core.config import settings

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _extract_email(payload: object) -> str | None:
    """Recursively find the first valid email in any verbatim Treg provider response."""
    if isinstance(payload, str):
        match = EMAIL_RE.search(payload)
        return match.group(0).lower() if match else None
    if isinstance(payload, dict):
        # Prioritize explicit email keys first
        for key in ("email", "contact_email", "work_email", "value"):
            val = payload.get(key)
            if isinstance(val, str) and EMAIL_RE.fullmatch(val.strip()):
                return val.strip().lower()
        for val in payload.values():
            found = _extract_email(val)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_email(item)
            if found:
                return found
    return None


async def enrich_company_waterfall(domain: str) -> tuple[dict | None, float]:
    if not settings.treg_api_key:
        print("[treg] Missing TREG_API_KEY; skipping enrichment", flush=True)
        return None, 0.0

    base_url = settings.treg_base_url.rstrip("/")
    headers = {
        "X-Treg-Token": settings.treg_api_key,
        "Content-Type": "application/json",
    }

    # Replace endpoint IDs below with your exact Treg catalog endpoint IDs (from `treg catalog find`)
    providers = [
        {"endpoint": "hunter/domain-search", "method": "GET", "params": {"domain": domain}, "est_cost": 0.01},
        {"endpoint": "apollo/organizations/enrich", "method": "GET", "params": {"domain": domain}, "est_cost": 0.015},
    ]

    total_cost = 0.0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for provider in providers:
            url = f"{base_url}/call/{provider['endpoint'].lstrip('/')}"
            try:
                if provider.get("method", "POST").upper() == "GET":
                    resp = await client.get(url, headers=headers, params=provider.get("params", {"domain": domain}))
                else:
                    resp = await client.post(url, headers=headers, json=provider.get("json", {"domain": domain}))

                # Treg reports actual metered cost in X-Treg-Cost-Micro header
                cost_micro = resp.headers.get("X-Treg-Cost-Micro")
                if cost_micro and cost_micro.isdigit():
                    total_cost += int(cost_micro) / 1_000_000
                elif resp.status_code == 200:
                    total_cost += float(provider["est_cost"])

                if resp.status_code != 200:
                    print(f"[treg] {provider['endpoint']} for {domain} -> {resp.status_code}: {resp.text[:160]}", flush=True)
                    continue

                data = resp.json()
                email = _extract_email(data)
                if email:
                    return {"email": email, "raw_enrichment": data}, round(total_cost, 6)

            except httpx.HTTPError as exc:
                print(f"[treg] HTTP error on {provider['endpoint']} for {domain}: {exc}", flush=True)
                continue

    return None, round(total_cost, 6)