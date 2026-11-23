import hashlib
import os
import secrets
from psycopg_pool import AsyncConnectionPool


def get_database_url() -> str:
    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if raw_url.startswith("DATABASE_URL="):
        raw_url = raw_url.split("=", 1)[1].strip()
    raw_url = raw_url.strip('"').strip("'")
    if not raw_url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            "Invalid DATABASE_URL: must start with 'postgresql://' or 'postgres://'."
        )
    return raw_url


def create_db_pool() -> AsyncConnectionPool:
    conninfo = get_database_url()
    return AsyncConnectionPool(
        conninfo=conninfo,
        open=False,
        kwargs={"autocommit": True},
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return secrets.compare_digest(dk.hex(), expected_hex)
    except ValueError:
        return False


async def init_app_tables(pool: AsyncConnectionPool) -> None:
    """Create users, customer_profiles, and run_history tables if they don't exist."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                company TEXT NOT NULL DEFAULT 'Workspace',
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS customer_profiles (
                id TEXT PRIMARY KEY,
                user_email TEXT,
                name TEXT NOT NULL,
                industry TEXT NOT NULL DEFAULT 'General B2B',
                size TEXT NOT NULL DEFAULT 'Any size',
                region TEXT NOT NULL DEFAULT 'Global',
                max_leads INTEGER NOT NULL DEFAULT 3,
                query TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS run_history (
                id TEXT PRIMARY KEY,
                user_email TEXT,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                leads_count INTEGER NOT NULL DEFAULT 0,
                spent_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )