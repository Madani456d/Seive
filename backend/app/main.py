import asyncio
import os
import sys
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load backend/.env explicitly before importing config/database/graph modules
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH, override=True)

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.agent.graph import build_graph  # noqa: E402
from app.core.auth import create_access_token, decode_access_token, get_current_user  # noqa: E402
from app.core.budget import BudgetExceededError  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.tables import hash_password, init_app_tables, verify_password  # noqa: E402


# ---------- Request Models ----------
class StartRunRequest(BaseModel):
    icp_query: str = Field(..., min_length=2, max_length=500)
    max_leads: int = Field(default=5, ge=1, le=25)


class ApproveRunRequest(BaseModel):
    approved: bool = True
    approved_leads: list[dict] | None = None
    approved_domains: list[str] | None = None


class AuthRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=160)
    password: str = Field(..., min_length=4, max_length=128)
    company: str = Field(default="Workspace", max_length=160)


class AuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    password: str = Field(..., min_length=1, max_length=128)


class ProfileCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    industry: str = Field(default="General B2B", max_length=120)
    size: str = Field(default="Any size", max_length=80)
    region: str = Field(default="Global", max_length=80)
    max_leads: int = Field(default=5, ge=1, le=25)
    query: str = Field(..., min_length=2, max_length=500)


def get_optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        return decode_access_token(token)
    except Exception:
        return None


def _resolve_db_url() -> str:
    candidate = (
        os.getenv("DATABASE_URL")
        or getattr(settings, "database_url", None)
        or getattr(settings, "DATABASE_URL", "")
        or ""
    ).strip()
    if candidate.startswith("DATABASE_URL="):
        candidate = candidate.split("=", 1)[1].strip()
    candidate = candidate.strip('"').strip("'")
    if not candidate.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            "Invalid DATABASE_URL: expected a connection string starting with 'postgresql://' or 'postgres://'."
        )
    if "supabase.com" in candidate and "sslmode=" not in candidate:
        sep = "&" if "?" in candidate else "?"
        candidate = f"{candidate}{sep}sslmode=require"
    return candidate


def _extract_leads(vals: dict, payload_dict: dict | None = None) -> list[dict]:
    p = payload_dict or {}
    return (
        p.get("prefiltered_leads")
        or p.get("pending_leads")
        or p.get("leads")
        or p.get("candidates")
        or vals.get("prefiltered_leads")
        or vals.get("filtered_leads")
        or vals.get("candidate_leads")
        or vals.get("raw_leads")
        or []
    )


async def _upsert_run_history(
    pool: AsyncConnectionPool,
    *,
    run_id: str,
    user_email: str | None,
    query: str,
    run_status: str,
    leads_count: int,
    spent_usd: float,
) -> None:
    if not user_email:
        return
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO run_history (id, user_email, query, status, leads_count, spent_usd)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET status = EXCLUDED.status,
                leads_count = EXCLUDED.leads_count,
                spent_usd = EXCLUDED.spent_usd
            """,
            (run_id, user_email, query, run_status, leads_count, spent_usd),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    conninfo = _resolve_db_url()
    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=2,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    try:
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        await init_app_tables(pool)
    except Exception:
        print("STARTUP ERROR IN LIFESPAN:", flush=True)
        traceback.print_exc()
        try:
            await pool.close()
        except Exception:
            pass
        raise

    app.state.pool = pool
    app.state.graph = build_graph(checkpointer=checkpointer)
    try:
        yield
    finally:
        await pool.close()


is_dev = os.getenv("ENV", "production").lower() in ("dev", "development", "local")
app = FastAPI(
    title="Lead Intelligence Platform",
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None,
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [
    origin.strip()
    for origin in allowed_origins_env.split(",")
    if origin.strip()
] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mock_mode": bool(settings.mock_mode or getattr(settings, "mock_treg", False)),
    }


# ---------- AUTH ENDPOINTS ----------
@app.post("/auth/register")
async def register(req: AuthRegisterRequest):
    email = req.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email address")

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(req.password)
    clean_name = req.name.strip() or email.split("@")[0]
    clean_company = req.company.strip() or "Workspace"

    async with app.state.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if await cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already registered. Please sign in.",
                )

            await cur.execute(
                """
                INSERT INTO users (id, name, email, company, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, email, company
                """,
                (user_id, clean_name, email, clean_company, pw_hash),
            )
            created = await cur.fetchone()

    user_payload = {
        "id": created["id"],
        "name": created["name"],
        "email": created["email"],
        "company": created["company"],
    }
    return {
        "access_token": create_access_token(user_payload),
        "token_type": "bearer",
        "user": user_payload,
    }


@app.post("/auth/login")
async def login(req: AuthLoginRequest):
    email = req.email.strip().lower()
    async with app.state.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, name, email, company, password_hash FROM users WHERE email = %s",
                (email,),
            )
            user = await cur.fetchone()

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user_payload = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "company": user["company"],
    }
    return {
        "access_token": create_access_token(user_payload),
        "token_type": "bearer",
        "user": user_payload,
    }


@app.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["sub"],
        "name": current_user["name"],
        "email": current_user["email"],
        "company": current_user["company"],
    }


# ---------- CUSTOMER PROFILES ENDPOINTS ----------
@app.get("/profiles")
async def list_profiles(current_user: dict = Depends(get_current_user)):
    async with app.state.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, name, industry, size, region, max_leads AS "maxLeads", query
                FROM customer_profiles
                WHERE user_email = %s
                ORDER BY created_at DESC
                """,
                (current_user["email"],),
            )
            return await cur.fetchall()


@app.post("/profiles")
async def create_profile(
    req: ProfileCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    profile_id = f"p-{uuid.uuid4().hex[:8]}"
    async with app.state.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO customer_profiles (id, user_email, name, industry, size, region, max_leads, query)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, industry, size, region, max_leads AS "maxLeads", query
                """,
                (
                    profile_id,
                    current_user["email"],
                    req.name.strip(),
                    req.industry.strip() or "General B2B",
                    req.size.strip() or "Any size",
                    req.region.strip() or "Global",
                    req.max_leads,
                    req.query.strip(),
                ),
            )
            return await cur.fetchone()


@app.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
):
    async with app.state.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "DELETE FROM customer_profiles WHERE id = %s AND user_email = %s RETURNING id",
                (profile_id, current_user["email"]),
            )
            deleted = await cur.fetchone()
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return {"deleted": True, "id": profile_id}


# ---------- RUN HISTORY ENDPOINTS ----------
@app.get("/history")
async def list_history(current_user: dict = Depends(get_current_user)):
    async with app.state.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, query, status, leads_count AS "leadsCount", spent_usd AS spent,
                       TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI') AS date
                FROM run_history
                WHERE user_email = %s
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (current_user["email"],),
            )
            return await cur.fetchall()


@app.delete("/history")
async def clear_history(current_user: dict = Depends(get_current_user)):
    async with app.state.pool.connection() as conn:
        await conn.execute(
            "DELETE FROM run_history WHERE user_email = %s",
            (current_user["email"],),
        )
    return {"cleared": True}


# ---------- AGENT RUN ENDPOINTS ----------
@app.post("/runs")
async def start_run(
    req: StartRunRequest,
    current_user: dict | None = Depends(get_optional_user),
):
    t0 = time.perf_counter()
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    clean_query = req.icp_query.strip()
    owner_email = (current_user or {}).get("email")

    initial_state = {
        "run_id": run_id,
        "user_email": owner_email or "",
        "user_query": clean_query,
        "max_leads": req.max_leads,
        "budget_spent_usd": 0.0,
    }

    print(f"[runs:{run_id}] Starting ainvoke", flush=True)
    try:
        await asyncio.wait_for(
            app.state.graph.ainvoke(initial_state, config=config),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Graph ainvoke timed out after {time.perf_counter() - t0:.1f}s",
        )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))

    print(f"[runs:{run_id}] ainvoke done at {time.perf_counter() - t0:.2f}s; fetching state", flush=True)
    snapshot = await app.state.graph.aget_state(config)
    vals = snapshot.values or {}
    spent = float(vals.get("budget_spent_usd", 0.0))

    if snapshot.tasks and snapshot.tasks[0].interrupts:
        payload = snapshot.tasks[0].interrupts[0].value
        payload_dict = payload if isinstance(payload, dict) else {"message": payload}
        leads = _extract_leads(vals, payload_dict)

        await _upsert_run_history(
            app.state.pool,
            run_id=run_id,
            user_email=owner_email,
            query=clean_query,
            run_status="awaiting_approval",
            leads_count=len(leads),
            spent_usd=spent,
        )
        print(f"[runs:{run_id}] Completed awaiting_approval in {time.perf_counter() - t0:.2f}s", flush=True)

        return {
            **payload_dict,
            "run_id": run_id,
            "status": "awaiting_approval",
            "icp_plan": vals.get("icp_plan"),
            "prefiltered_leads": leads,
            "budget_spent_usd": spent,
        }

    scored_leads = vals.get("scored_leads", [])
    await _upsert_run_history(
        app.state.pool,
        run_id=run_id,
        user_email=owner_email,
        query=clean_query,
        run_status="completed",
        leads_count=len(scored_leads),
        spent_usd=spent,
    )

    return {
        "run_id": run_id,
        "status": "completed",
        "icp_plan": vals.get("icp_plan"),
        "budget_spent_usd": spent,
        "scored_leads": scored_leads,
    }


@app.post("/runs/{run_id}/approve")
async def approve_run(
    run_id: str,
    req: ApproveRunRequest,
    current_user: dict | None = Depends(get_optional_user),
):
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await app.state.graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    owner_email = (snapshot.values.get("user_email") or "").strip().lower()
    caller_email = ((current_user or {}).get("email") or "").strip().lower()
    if owner_email and owner_email != caller_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this run")

    resume_payload: dict = {"approved": req.approved}

    if req.approved:
        if req.approved_leads is not None:
            resume_payload["approved_leads"] = req.approved_leads
        elif req.approved_domains is not None:
            allowed = {d.strip().lower() for d in req.approved_domains}
            current_leads = _extract_leads(snapshot.values)
            resume_payload["approved_leads"] = [
                lead for lead in current_leads
                if lead.get("domain", "").strip().lower() in allowed
            ]
    else:
        resume_payload["approved_leads"] = []

    try:
        result = await app.state.graph.ainvoke(Command(resume=resume_payload), config=config)
    except BudgetExceededError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))

    final_status = "completed" if req.approved else "rejected"
    scored_leads = result.get("scored_leads", [])
    spent = float(result.get("budget_spent_usd", 0.0))

    await _upsert_run_history(
        app.state.pool,
        run_id=run_id,
        user_email=owner_email or None,
        query=snapshot.values.get("user_query", ""),
        run_status=final_status,
        leads_count=len(scored_leads),
        spent_usd=spent,
    )

    return {
        "run_id": run_id,
        "status": final_status,
        "budget_spent_usd": spent,
        "scored_leads": scored_leads,
    }


@app.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    current_user: dict | None = Depends(get_optional_user),
):
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await app.state.graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    vals = snapshot.values
    owner_email = (vals.get("user_email") or "").strip().lower()
    caller_email = ((current_user or {}).get("email") or "").strip().lower()
    if owner_email and owner_email != caller_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this run")

    is_paused = bool(snapshot.tasks and snapshot.tasks[0].interrupts)
    return {
        "run_id": run_id,
        "status": "awaiting_approval" if is_paused else "completed",
        "icp_plan": vals.get("icp_plan"),
        "prefiltered_leads": _extract_leads(vals),
        "scored_leads": vals.get("scored_leads", []),
        "budget_spent_usd": vals.get("budget_spent_usd", 0.0),
    }
