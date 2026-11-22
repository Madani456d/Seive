import json
from typing import Optional
from app.db.supabase_client import get_db_pool
from app.schemas.lead import EnrichedLead


async def init_cache_table() -> None:
    pool = await get_db_pool()
    async with pool.connection() as conn:
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS lead_cache (
                domain TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            '''
        )


async def get_cached_lead(domain: str) -> Optional[EnrichedLead]:
    pool = await get_db_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT payload FROM lead_cache WHERE domain = %s;", (domain,)
        )
        row = await cur.fetchone()
        if row and row.get("payload"):
            return EnrichedLead.model_validate(row["payload"])
    return None


async def save_cached_lead(lead: EnrichedLead) -> None:
    pool = await get_db_pool()
    async with pool.connection() as conn:
        await conn.execute(
            '''
            INSERT INTO lead_cache (domain, payload, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (domain)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW();
            ''',
            (lead.domain, json.dumps(lead.model_dump())),
        )
