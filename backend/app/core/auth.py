import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def _secret_key() -> bytes:
    secret = (
        getattr(settings, "auth_secret_key", "")
        or os.getenv("AUTH_SECRET_KEY", "")
        or settings.database_url
    )
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def create_access_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": str(user["id"]),
        "email": str(user["email"]).lower().strip(),
        "name": str(user.get("name") or ""),
        "company": str(user.get("company") or ""),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)
    sig = hmac.new(_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64_encode(sig)}"


def decode_access_token(token: str) -> dict[str, Any]:
    if not token or "." not in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        )
    payload_b64, sig_b64 = token.split(".", 1)
    expected_sig = hmac.new(
        _secret_key(), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        actual_sig = _b64_decode(sig_b64)
        payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token",
        )

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
        )
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again",
        )
    return payload


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return decode_access_token(credentials.credentials)