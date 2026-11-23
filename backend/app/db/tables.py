import hashlib
import os
import hmac


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, digest = stored_hash.split("$", 1)
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return hmac.compare_digest(check, digest)


async def init_app_tables(pool) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT UNIQUE NOT NULL,
            company TEXT,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS run_history (
            id TEXT PRIMARY KEY,
            user_email TEXT,
            query TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            leads_count INTEGER NOT NULL DEFAULT 0,
            spent_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
    ]

    async with pool.connection() as conn:
        for sql in statements:
            await conn.execute(sql)