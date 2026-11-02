"""Login and token handling. Tokens carry only `sub` (user_id) and `exp`.

Role and requisition access are never in the token; app/security.py looks them up per request,
so a role change or reassignment takes effect on the next request, not at token expiry.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings

ALGORITHM = "HS256"
BCRYPT_MAX_BYTES = 72  # bcrypt 5 raises above this; older versions silently truncated

router = APIRouter()


class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    password: str  # no max_length: a 422 would echo the password back in the error body


class LoginThrottle:
    """Failed-login limiter keyed on the normalised email (known or not, so it can't enumerate).

    After `max_failures` failures inside `window` seconds the email is refused with 429 until the
    oldest failure ages out. In-memory and per process: enough for one instance; a multi-instance
    deploy needs a shared store. Trade-off: anyone can lock an account for up to `window` seconds.
    """

    def __init__(self, max_failures: int, window: float):
        self.max_failures, self.window = max_failures, window
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        q = self._fails.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            q = self._recent(key, now)
            if len(q) >= self.max_failures:
                return max(1, int(q[0] + self.window - now) + 1)
            if not q:
                self._fails.pop(key, None)
            return None

    def failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._recent(key, now).append(now)

    def success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


def normalise_email(email: str) -> str:
    return email.strip().lower()


class Credentials:
    """Demo credential store: every gold.dim_user email -> one bcrypt hash of NB_DEMO_PASSWORD."""

    def __init__(self, con, settings: Settings):
        self.password_hash = bcrypt.hashpw(
            settings.demo_password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
        )
        rows = con.execute("SELECT lower(trim(email)), user_id FROM gold.dim_user WHERE email IS NOT NULL").fetchall()
        self.user_by_email: dict[str, str] = {e: u for e, u in rows}

    def verify(self, email: str, password: str) -> str | None:
        user_id = self.user_by_email.get(normalise_email(email))
        pw = password.encode()
        # Always run bcrypt exactly once, known email or not, so response time doesn't reveal which
        # emails exist. An over-long password can't be right: hash a placeholder for equal timing
        # rather than truncating (which would let "<password>+junk" match).
        too_long = len(pw) > BCRYPT_MAX_BYTES
        ok = bcrypt.checkpw(b"x" if too_long else pw, self.password_hash) and not too_long
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
    throttle: LoginThrottle = request.app.state.login_throttle
    key = normalise_email(body.email)
    wait = throttle.retry_after(key)
    if wait is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many failed sign-in attempts; try later",
                            headers={"Retry-After": str(wait)})
    user_id = creds.verify(body.email, body.password)
    if user_id is None:
        throttle.failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    throttle.success(key)
    settings: Settings = request.app.state.settings
    return {
        "access_token": issue_token(user_id, settings),
        "token_type": "bearer",
        "expires_in": settings.token_ttl_minutes * 60,
    }

