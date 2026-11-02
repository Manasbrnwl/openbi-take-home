"""FastAPI app. Every data endpoint depends on get_principal/get_scope and filters in SQL.

Run:  NB_ENV=dev .venv/Scripts/python -m uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import metrics
from app.auth import Credentials
from app.auth import router as auth_router
from app.config import Settings
from app.db import get_con, open_warehouse, rows_as_dicts
from app.security import Principal, get_principal, get_scope
from metrics import Scope

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_PAGE_SIZE = 100

# Query params that must never reach a metric function, whatever the metric accepts.
# Scope comes from the token only; these names are dropped so nobody can try to smuggle one in.
RESERVED_METRIC_PARAMS = {"scope", "con", "name", "user_id", "role", "req_keys", "token"}

_APP_COLUMNS = """
    fa.application_id, fa.req_id, dr.title AS req_title, fa.applied_at, fa.current_stage,
    fa.is_orphan, dc.full_name AS candidate_name, dc.email AS candidate_email,
    dc.phone AS candidate_phone, dc.source AS candidate_source
"""
_APP_FROM = """
    FROM gold.fact_application fa
    JOIN gold.dim_requisition dr ON dr.req_key = fa.req_key
    LEFT JOIN gold.dim_candidate dc ON dc.candidate_key = fa.candidate_key
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        con = open_warehouse(settings.warehouse_path)
        app.state.con = con
        app.state.credentials = Credentials(con, settings)
        try:
            yield
        finally:
            con.close()

    app = FastAPI(title="Northbeam ATS analytics", lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        if not request.url.path.startswith("/static") and request.url.path != "/":
            resp.headers["Cache-Control"] = "no-store"  # responses carry scoped data and PII
        return resp

    app.include_router(auth_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz(con=Depends(get_con)):
        # Unauthenticated liveness check for the host; proves the warehouse is open, returns no data.
        con.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/me")
    def me(principal: Principal = Depends(get_principal), con=Depends(get_con)):
        where, params = principal.scope.sql_filter("req_key")
        (visible,) = con.execute(
            f"SELECT count(*) FROM gold.dim_requisition WHERE req_key >= 0 AND {where}", params
        ).fetchone()
        return {
            "user_id": principal.user_id,
            "name": principal.name,
            "email": principal.email,
            "role": principal.role,
            "department": principal.department,
            "visible_requisitions": visible,
        }

    @app.get("/metrics")
    def get_metric_list(_: Scope = Depends(get_scope)):
        return metrics.list_metrics()

    @app.get("/metrics/{name}")
    def get_metric(name: str, request: Request, scope: Scope = Depends(get_scope), con=Depends(get_con)):
        if name not in {m["name"] for m in metrics.list_metrics()}:
            raise HTTPException(404, "unknown metric")
        params = {k: v for k, v in request.query_params.items() if k not in RESERVED_METRIC_PARAMS}
        try:
            return metrics.compute(con, name, scope, **params)  # returned unchanged
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f"bad parameters for {name}: {e}") from None

    @app.get("/requisitions")
    def list_requisitions(scope: Scope = Depends(get_scope), con=Depends(get_con)):
        where, params = scope.sql_filter("dr.req_key")
        con.execute(
            f"""SELECT dr.req_id, dr.title, dr.department, dr.location, dr.status, dr.headcount,
                       dr.opened_date, dr.closed_date, dr.hiring_manager_id, dr.recruiter_id
                FROM gold.dim_requisition dr WHERE {where} ORDER BY dr.req_key""",
            params,
        )
        return rows_as_dicts(con)

    @app.get("/requisitions/{req_id}/applications")
    def requisition_applications(req_id: str, scope: Scope = Depends(get_scope), con=Depends(get_con)):
        where, params = scope.sql_filter("dr.req_key")
        row = con.execute(
            f"SELECT dr.req_key FROM gold.dim_requisition dr WHERE dr.req_id = ? AND {where}",
            [req_id, *params],
        ).fetchone()
        if row is None:
            # Same answer for "doesn't exist" and "not yours": existence isn't leaked.
            raise HTTPException(404, "requisition not found")
        con.execute(
            f"SELECT {_APP_COLUMNS} {_APP_FROM} WHERE fa.req_key = ? AND {where} ORDER BY fa.applied_at, fa.application_id",
            [row[0], *params],
        )
        return rows_as_dicts(con)

    @app.get("/applications")
    def list_applications(
        stage: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
        scope: Scope = Depends(get_scope),
        con=Depends(get_con),
    ):
        where, params = scope.sql_filter("fa.req_key")
        if stage:
            where += " AND fa.current_stage = ?"
            params = [*params, stage]
        (total,) = con.execute(f"SELECT count(*) {_APP_FROM} WHERE {where}", params).fetchone()
        con.execute(
            f"SELECT {_APP_COLUMNS} {_APP_FROM} WHERE {where} "
            "ORDER BY fa.applied_at DESC, fa.application_id LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {"page": page, "page_size": page_size, "total": total, "items": rows_as_dicts(con)}

    if FRONTEND_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    # `uvicorn app.main:app` works without building the app (and reading env) at import time,
    # so tests can import create_app with their own settings.
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
