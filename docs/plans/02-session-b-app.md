# Plan handed to session B — API, auth, access control, frontend

Owner: agent session `openbi-take-home-ca`. Coordinator: session A (`openbi-take-home-d3`),
which owns `pipeline/` and `metrics/`. Read `CLAUDE.md` and `docs/CONTRACT.md` first.

## Scope — you own `app/`, `frontend/`, `tests/test_access_*.py`, `tests/test_api_*.py`

1. **FastAPI app** `app/main.py`, reading `warehouse/northbeam.duckdb` **read-only**
   (path from env `NB_WAREHOUSE`, default `warehouse/northbeam.duckdb`).
2. **Auth** `app/auth.py`
   - `POST /auth/login {email, password}` → JWT (HS256, secret from env `NB_JWT_SECRET`;
     refuse to start if unset outside `NB_ENV=dev`), 60-min expiry, claims `sub` (user_id) + `exp` only.
     Do NOT put role or req ids in the token — they are looked up per request.
   - Demo credentials: every user in `gold.dim_user` gets password from env `NB_DEMO_PASSWORD`
     (default `northbeam-demo` in dev only), stored as a bcrypt hash computed at startup.
     Constant-time failure path for unknown emails.
3. **Scope** `app/security.py` — `get_scope(token) -> metrics.Scope`. The ONLY place a Scope is built.
   Rules are in CONTRACT.md. Unknown/deactivated user id → 401.
4. **Endpoints** (all require auth; all apply scope in SQL via `Scope.sql_filter`):
   - `GET /me` — user + role + visible req count
   - `GET /metrics` — list of metric definitions
   - `GET /metrics/{name}?<params>` — returns `metrics.compute(...)` output unchanged
   - `GET /requisitions` — scoped list
   - `GET /requisitions/{req_id}/applications` — 404 if req not in scope
   - `GET /applications?stage=&page=&page_size=` — scoped, paginated (max page_size 100)
   Candidate PII (email, phone) appears only on application rows the user is entitled to.
5. **Frontend** `frontend/index.html` (+ one JS file), served by FastAPI at `/`. Login form, 4–5
   metric tiles, one table of applications. Render values exactly as the API returns them.
   Plain HTML/JS — visual design is not scored. No metric arithmetic, no `* 100`, no `toFixed`
   on values that change their meaning (formatting thousands separators is fine).
6. **Access-control tests** (the part that's actually scored): with TestClient prove that
   - HM U005 cannot see a req owned by another HM via `/requisitions/{id}/applications` (404)
   - tampering: forged JWT (wrong secret), `alg=none` token, expired token → 401
   - adding `?user_id=U001`, `?role=admin`, `X-User-Id` header changes nothing
   - metric values for an HM differ from admin and only include their reqs
   - recruiter sees exactly the reqs where `recruiter_id` = them
   - orphan applications visible to admin only
   Write a short section for README: "How we know access control can't be bypassed".

## Until the warehouse exists
Session A will ship `pipeline.run` shortly. Until then, build against the contract with a
tiny fixture DuckDB created in a pytest fixture (`tests/conftest.py`) matching the Gold columns
in CONTRACT.md. Metrics stub: `metrics.compute` raises KeyError until definitions land — mock it
in tests or just wire the route.

## Rules
- `git add` only your paths; small commits (`feat(app): …`, `test(access): …`).
- Don't edit `pipeline/`, `metrics/`, `docs/CONTRACT.md` — message session A if the contract
  needs to change.
- Log anything the coordinator should know (decisions, mistakes caught) in
  `docs/worklog-notes-session-b.md` — the human will use it for the worklog.
