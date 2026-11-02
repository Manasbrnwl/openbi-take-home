"""Login and token handling. Tokens carry only `sub` (user_id) and `exp`.

Role and requisition access are never in the token; app/security.py looks them up per request,
so a role change or reassignment takes effect on the next request, not at token expiry.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.config import Settings

ALGORITHM = "HS256"

router = APIRouter()


class LoginBody(BaseModel):
    email: str
    password: str


class Credentials:
    """Demo credential store: every gold.dim_user email -> one bcrypt hash of NB_DEMO_PASSWORD."""

    def __init__(self, con, settings: Settings):
        self.password_hash = bcrypt.hashpw(
            settings.demo_password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
        )
        rows = con.execute("SELECT lower(trim(email)), user_id FROM gold.dim_user WHERE email IS NOT NULL").fetchall()
        self.user_by_email: dict[str, str] = {e: u for e, u in rows}

    def verify(self, email: str, password: str) -> str | None:
        user_id = self.user_by_email.get(email.strip().lower())
        # Always run bcrypt, known email or not, so response time doesn't reveal which emails exist.
        ok = bcrypt.checkpw(password.encode(), self.password_hash)
        return user_id if (ok and user_id is not None) else None


def issue_token(user_id: str, settings: Settings) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.token_ttl_minutes)
    return jwt.encode({"sub": user_id, "exp": exp}, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, settings: Settings) -> str:
    """Return the verified user_id, or raise jwt.InvalidTokenError."""
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],  # pinned: rejects alg=none and any other algorithm
        options={"require": ["sub", "exp"]},
    )
    sub = claims["sub"]
    if not isinstance(sub, str) or not sub:
        raise jwt.InvalidTokenError("bad sub")
    return sub


@router.post("/auth/login")
def login(body: LoginBody, request: Request):
    creds: Credentials = request.app.state.credentials
    user_id = creds.verify(body.email, body.password)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    settings: Settings = request.app.state.settings
    return {
        "access_token": issue_token(user_id, settings),
        "token_type": "bearer",
        "expires_in": settings.token_ttl_minutes * 60,
    }

