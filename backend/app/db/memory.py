import json
from typing import Any, Dict
from app.db.supabase_client import get_db_pool


async def init_memory_table() -> None:
    pool = await get_db_pool()
    async with pool.connection() as conn:
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                user_query TEXT NOT NULL,
                summary JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            '''
        )


async def log_agent_run(run_id: str, user_query: str, summary: Dict[str, Any]) -> None:
    pool = await get_db_pool()
    async with pool.connection() as conn:
        await conn.execute(
            '''
            INSERT INTO agent_runs (run_id, user_query, summary)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (run_id)
            DO UPDATE SET summary = EXCLUDED.summary;
            ''',
            (run_id, user_query, json.dumps(summary)),
        )
