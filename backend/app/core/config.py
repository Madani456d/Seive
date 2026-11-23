import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH, override=True)


def _get_env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip().strip('"').strip("'")


def _get_float_env(name: str, default: float) -> float:
    val = _get_env(name, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _build_database_url() -> str:
    raw_url = _get_env("DATABASE_URL")
    if not raw_url:
        raise RuntimeError(f"DATABASE_URL is missing or empty in {ENV_PATH}")
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql://" + raw_url[len("postgres://") :]
    if ("supabase.co" in raw_url or "pooler.supabase.com" in raw_url) and "sslmode=" not in raw_url:
        sep = "&" if "?" in raw_url else "?"
        raw_url = f"{raw_url}{sep}sslmode=require"
    return raw_url


class Settings:
    database_url: str = _build_database_url()
    mock_mode: bool = _get_env("MOCK_MODE", "false").lower() in ("1", "true", "yes")
    mock_treg: bool = _get_env("MOCK_TREG", "false").lower() in ("1", "true", "yes")
    max_run_budget_usd: float = _get_float_env("MAX_RUN_BUDGET_USD", 1.0)
    gemini_api_key: str = _get_env("GEMINI_API_KEY") or _get_env("GOOGLE_API_KEY")
    gemini_planner_model: str = _get_env("GEMINI_PLANNER_MODEL", "gemini-3.8-flash")
    gemini_fast_model: str = _get_env("GEMINI_FAST_MODEL", "gemini-3.1-flash-lite")
    openai_api_key: str = _get_env("OPENAI_API_KEY")
    tavily_api_key: str = _get_env("TAVILY_API_KEY")

settings = Settings()