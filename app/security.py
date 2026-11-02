"""The ONLY place a metrics.Scope is built.

Input: the bearer token. Output: who the caller is and which req_keys they may see, looked up in
gold.dim_user / gold.dim_requisition. Nothing from the query string, headers (other than the
Authorization bearer token) or body is read here, so a request can't widen its own scope.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import decode_token
from app.db import get_con
from metrics import Scope

_bearer = HTTPBearer(auto_error=False)

# Which dim_requisition column ties a non-admin role to its requisitions (CONTRACT.md).
_ROLE_REQ_COLUMN = {
    "hiring_manager": "hiring_manager_id",
    "recruiter": "recruiter_id",
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    email: str
    role: str
    department: str | None
    scope: Scope


def _unauthorized(detail: str = "not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def build_scope(con, user_id: str) -> Principal:
    row = con.execute(
        "SELECT user_id, name, email, role, department FROM gold.dim_user WHERE user_id = ?", [user_id]
    ).fetchone()
    if row is None:
        raise _unauthorized("unknown user")
    uid, name, email, role, department = row

    if role == "admin":
        req_keys = None  # unrestricted: all requisitions plus orphans
    elif role in _ROLE_REQ_COLUMN:
        col = _ROLE_REQ_COLUMN[role]  # from a fixed dict, never from input
        keys = con.execute(
            f"SELECT req_key FROM gold.dim_requisition WHERE {col} = ? AND req_key >= 0", [uid]
        ).fetchall()
        req_keys = frozenset(k for (k,) in keys)
    else:
        # A role we don't know how to scope gets nothing, not everything.
        raise _unauthorized("role not permitted")

    return Principal(uid, name, email, role, department, Scope(user_id=uid, role=role, req_keys=req_keys))


def get_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    con=Depends(get_con),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        user_id = decode_token(creds.credentials, request.app.state.settings)
    except jwt.InvalidTokenError:
        raise _unauthorized("invalid or expired token") from None
    return build_scope(con, user_id)


def get_scope(principal: Principal = Depends(get_principal)) -> Scope:
    return principal.scope
