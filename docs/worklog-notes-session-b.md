# Session B worklog notes (API, auth, access control, frontend)

## Decisions

- **`NB_ENV` defaults to prod, not dev.** A bare `uvicorn app.main:app` refuses to start without
  `NB_JWT_SECRET` and `NB_DEMO_PASSWORD`. For local runs, set `NB_ENV=dev`. In dev the JWT secret
  is random per process (tokens die on restart or `--reload`), so no hard-coded secret exists that
  could sign a token.
- **`app.main:app` is lazy** (module `__getattr__`). Tests import `create_app(settings)` without
  reading env, and uvicorn still finds `app`.
- **Unknown roles get 401**, not an empty scope and not everything. This fails closed.
- **Metric query params pass straight through** to `metrics.compute`, minus a denylist of
  identity-like names. `TypeError`/`ValueError` from a metric becomes 400. I chose this so the app
  doesn't duplicate each metric's parameter list. The scope can't be overridden anyway, because
  `scope` is a positional argument.
- **The frontend renders every metric in `/metrics`, in order**, rather than a hard-coded five. Extra
  return fields (`previous`, `change`, `change_percent`, `accepted`, `hires`, …) are shown as
  delivered. Formatting is `Intl.NumberFormat("en-IN")` with `maximumFractionDigits: 20`, which
  adds separators and never rounds.
- **`/healthz` is unauthenticated** (Render health check). It runs `SELECT 1` and returns no data.
- **`tests/conftest.py`** holds a fixture Gold warehouse, so the access tests don't depend on the
  pipeline. The same invariants are re-checked on the real warehouse when it exists.
- Design: I loaded `design-taste-frontend` and read the app-screen sections that applied (KPIs,
  tables, tokens, states, house rules). I used its default app tokens. I did not deal a direction
  with `draw.mjs` or run `inspect.mjs`: the visual design isn't scored, and the CSP rules out
  webfonts anyway.

## Mistakes I caught in my own work

1. **Sign-out leaked the previous user's view state.** Found in the browser QA pass with duet. As
   HM U005 I filtered applications to "Offer", signed out, and signed in as admin. The admin table
   read "1–25 of 132" instead of 1,450. `signOut()` cleared the token and DOM but not `state.stage`
   or the `<select>`. It wasn't a data leak (132 was admin's own scoped Offer count), but the second
   user saw a filtered view they didn't choose. Fixed by resetting page, stage and the select on
   sign-out. Re-tested with the same sequence: admin got "1–25 of 1,450" and "All stages".
2. **Horizontal overflow on narrow screens.** Also found in duet, at about 500px wide. `.canvas` is
   a CSS grid whose implicit column grew to the applications table's min-content width, which
   pushed the metric cards off-screen. Fixed with `grid-template-columns: minmax(0, 1fr)` (and
   `min(280px, 100%)` on the card grid). Measured after the fix: no page overflow; the table
   scrolls inside its own panel.
3. **My first mutation-test numbers weren't clean.** I applied the "403 instead of 404" breakage on
   top of the "params unfiltered" breakage without restoring in between, so the reported 11
   failures was a combined number. I re-ran all four breakages one at a time against the current
   suite (23 / 7 / 3 / 12 of 54). `docs/ACCESS_CONTROL.md` uses the clean numbers.
4. **First mutation run showed "2 errors" instead of failures** for the everyone-is-admin breakage.
   That came from running the whole suite while session A's pipeline tests were using the
   warehouse file, not from the breakage itself. Run against the app tests alone, it fails 23.
   Lesson: run mutation checks against the app test files only.
5. Small: my first `app/auth.py` had a leftover `import hmac`, and a db dependency on `/auth/login`
   that it didn't use. Removed before the first commit.

## Not verified

- Light colour scheme: the QA browser rendered dark mode. Light tokens exist but I didn't screenshot them.

## For session A

- The app holds a read-only DuckDB handle, so stop uvicorn before re-running `pipeline.run` on Windows.
- Breakdown columns have no units (e.g. offer acceptance `rate` prints `52`, not `52%`). If you want
  units there, a per-column unit map in the result would let the frontend label them without guessing.

## Extension C: security review (docs/SECURITY_REVIEW.md)

- Four findings, each reproduced by a probe, then a test written failing first, then the fix:
  SR-1 unlimited login guessing (High), SR-2 over-long password returns 500 and can match by
  prefix on bcrypt 4.x (Medium), SR-3 authenticated inputs that crash the server and error text
  that names internals (Low), SR-4 public OpenAPI/docs (Low).
  16 of 18 new tests failed before the fixes; all pass after. Full suite: 85.
- Ruled out with evidence: SQL injection through metric params (all bound), `**params` overriding
  scope, login timing difference (0.248 vs 0.240s), PII in metric breakdowns (0 of 560
  candidates' values found).
- **Mistake caught:** my first SR-2 fix capped the password at 1,024 characters with Pydantic. The
  10,000-byte test then returned 422 instead of 401, and FastAPI's 422 body echoes the submitted
  input, so the fix would have sent the password back in the response. I replaced it with the
  length check inside `verify` and verified the password is not echoed.
- **Mistake caught:** my original `Credentials.verify` comment said bcrypt ran "known email or not"
  for equal timing, but I had never checked what bcrypt does above 72 bytes. On bcrypt 4.x it
  truncates, and `requirements.txt` still allows 4.x. I've recommended pinning `bcrypt>=5` to
  session A, which owns requirements.
- Not done: `pip-audit` (not installed; offline).
