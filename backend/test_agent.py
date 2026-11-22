import asyncio
import uuid
from app.agent.graph import build_graph
from app.db.supabase_client import get_checkpointer, close_db_pool
from app.db.cache import init_cache_table
from app.db.memory import init_memory_table, log_agent_run

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main():
    await init_cache_table()
    await init_memory_table()

    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer=checkpointer)

    run_id = str(uuid.uuid4())
    query = "Find B2B SaaS developer tools startups with 10-200 employees"

    result = await graph.ainvoke(
        {
            "run_id": run_id,
            "user_query": query,
            "budget_spent_usd": 0.0,
            "hitl_approved": True,
            "errors": [],
        },
        config={"configurable": {"thread_id": run_id}},
    )

    scored = result.get("scored_leads", [])
    print(f"\nRun ID: {run_id}")
    print(f"Budget Spent: ${result.get('budget_spent_usd', 0.0):.4f}")
    print(f"Scored Leads ({len(scored)}):")
    for lead in scored:
        print(f"  - [{lead.fit_score}/100] {lead.company_name} ({lead.email})")
        print(f"    Angle: {lead.outreach_angle}")

    await log_agent_run(
        run_id,
        query,
        {"lead_count": len(scored), "budget_spent_usd": result.get("budget_spent_usd", 0.0)},
    )
    await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())