import asyncio
import sys
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from app.agent.graph import build_graph
from app.core.config import settings

# Required on Windows for psycopg async compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class StartRunRequest(BaseModel):
    icp_query: str = Field(..., examples=["B2B SaaS DevTools startups in US with 10-50 employees"])
    max_leads: int = Field(default=5, ge=1, le=25)

class ApproveRunRequest(BaseModel):
    approved: bool = True
    approved_leads: list[dict] | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"approved": True}]
        }
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    app.state.pool = pool
    app.state.graph = build_graph(checkpointer=checkpointer)
    yield
    await pool.close()


app = FastAPI(title="LeadGen Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": settings.mock_mode}


@app.post("/runs")
async def start_run(req: StartRunRequest):
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    initial_state = {
        "run_id": run_id,
        "user_query": req.icp_query,
        "max_leads": req.max_leads,
        "budget_spent_usd": 0.0,
     }

    await app.state.graph.ainvoke(initial_state, config=config)
    snapshot = await app.state.graph.aget_state(config)

    # Check if paused at hitl_gate interrupt
    if snapshot.tasks and snapshot.tasks[0].interrupts:
        payload = snapshot.tasks[0].interrupts[0].value
        return {
            "run_id": run_id,
            "status": "awaiting_approval",
            **payload,
        }

    return {
        "run_id": run_id,
        "status": "completed",
        "budget_spent_usd": snapshot.values.get("budget_spent_usd", 0.0),
        "scored_leads": snapshot.values.get("scored_leads", []),
    }


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, req: ApproveRunRequest):
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await app.state.graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Run not found")

    resume_payload = {"approved": req.approved}
    if req.approved_leads is not None:
        resume_payload["approved_leads"] = req.approved_leads

    result = await app.state.graph.ainvoke(Command(resume=resume_payload), config=config)

    return {
        "run_id": run_id,
        "status": "completed" if req.approved else "rejected",
        "budget_spent_usd": result.get("budget_spent_usd", 0.0),
        "scored_leads": result.get("scored_leads", []),
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await app.state.graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Run not found")

    is_paused = bool(snapshot.tasks and snapshot.tasks[0].interrupts)
    return {
        "run_id": run_id,
        "status": "awaiting_approval" if is_paused else "completed",
        "budget_spent_usd": snapshot.values.get("budget_spent_usd", 0.0),
        "scored_leads": snapshot.values.get("scored_leads", []),
    }
