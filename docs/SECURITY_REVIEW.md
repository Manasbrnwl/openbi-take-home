# Security review: Northbeam ATS analytics

Reviewed: the API (`app/`), the frontend (`frontend/`), and how the metric layer (`metrics/`) handles
request parameters. Method: read the code, then probe the running app with `TestClient` against the
real warehouse. Every finding was reproduced first, then a regression test was written and shown to
fail before the fix and pass after it (`tests/test_security_review.py`).

| ID | Finding | Severity | Status |
|---|---|---|---|
| SR-1 | Unlimited password guessing on `/auth/login` | **High** | Fixed |
| SR-2 | Over-long passwords: unauthenticated 500, and a prefix-match risk on bcrypt 4.x | **Medium** | Fixed |
| SR-3 | Authenticated inputs that crash the server, and error text that names internals | **Low** | Fixed |
| SR-4 | API schema and interactive docs published to anonymous users | **Low** | Fixed |

---

## SR-1: Unlimited password guessing (High)

**What.** `/auth/login` had no limit on failed attempts. Every demo user shares one password
(`NB_DEMO_PASSWORD`), and the login page lists the admin's email. So one successful guess opens
every account, admin included.

**Evidence** (before fix, real warehouse, one client, no parallelism):

```
30 wrong attempts: {401} in 7.4s
then right pw: 200
```

About 4 guesses per second from a single connection, with nothing slowing it down.

**Fix.** `app/auth.py::LoginThrottle`. After 5 failures within 15 minutes for one email, that email
gets `429` with a `Retry-After` header, including when the password is correct, so guessing can't
continue. A successful login clears the counter. The key is the normalised email (trimmed,
lowercased), and unknown emails are throttled the same way, so the 401/429 pattern doesn't reveal
which emails exist. Limits are configurable (`NB_LOGIN_MAX_FAILURES`, `NB_LOGIN_WINDOW_SECONDS`).

**Proof.** `test_sr1_login_locks_after_repeated_failures`,
`test_sr1_throttle_does_not_reveal_which_emails_exist`, `test_sr1_throttle_key_is_normalised`,
`test_sr1_success_resets_the_counter`. Three of these failed before the fix (the counter-reset test
passes trivially without a throttle). After the fix, on the real warehouse:
`brute force: [401, 401, 401, 401, 401, 429, 429]`.

**Residual risk, accepted.** Anyone who knows an email can lock that account for up to 15 minutes;
that's the usual trade-off of per-account lockout. The counter lives in memory per process, which is
right for the single instance deployed here; more instances would need a shared store such as Redis.
It is not keyed on client IP because behind Render's proxy every client shares one address.

## SR-2: Over-long passwords (Medium)

**What.** bcrypt only uses the first 72 bytes of a password. With bcrypt 5.0.0 (installed),
`checkpw` raises `ValueError` above 72 bytes. Nothing caught it, so any anonymous client got a 500
from the login endpoint, with a traceback in the server log for each request. With bcrypt 4.x,
which `requirements.txt` still allows (`bcrypt>=4.2`), the library **silently truncates** instead.
There, the real password plus any junk would be accepted, and so would any string sharing the first
72 bytes.

**Evidence** (before fix):

```
long pw  : 500 'Internal Server Error'          # known email, 73 bytes
long pw unknown: 500 'Internal Server Error'    # unknown email, 200 bytes
```

**Fix.** `Credentials.verify` rejects any password over 72 bytes. It still runs exactly one bcrypt
check (on a placeholder), so timing matches the normal failure path, and it returns the same 401. I
first capped the field length with Pydantic instead. I backed that out because FastAPI's 422 body
echoes the submitted input, which would have sent the password back in the response.

**Proof.** `test_sr2_overlong_password_is_401_not_500` (4 cases: known and unknown email, 73 and
10,000 bytes) and `test_sr2_overlong_password_never_matches_by_prefix` (correct 72-byte password →
200; same password plus `junk` → 401). All 5 failed before the fix and pass after. Re-probe: a
16,000-byte password gets 401 and doesn't appear in the response body.

## SR-3: Authenticated inputs that crash the server (Low)

**What.** Three inputs any signed-in user can send caused unhandled exceptions:

- `GET /applications?page=922337203685477580`: the computed `OFFSET` overflows DuckDB's `BIGINT`.
- Dates at the edge of the calendar, e.g. `/metrics/applications_received_mom?month=9999-12` or
  `/metrics/applications_at_stage_asof?as_of=9999-12-31`: the metric adds a day or a month and
  raises `OverflowError`, which the route didn't map to 400.
- Bad parameters that *were* mapped to 400 echoed the Python exception text, revealing internal
  function names: `unique_people() got an unexpected keyword argument 'bogus'`.

**Evidence** (before fix):

```
apps page=922337203685477580 : 500 'Internal Server Error'
metric applications_received_mom month=9999-12 : 500 'Internal Server Error'
metric applications_at_stage_asof as_of=9999-12-31 : 500 'Internal Server Error'
metric time_to_hire_median_days end=9999-12-31 : 500 'Internal Server Error'
metric unique_people bogus=1 : 400 "... unique_people() got an unexpected keyword argument 'bogus'"
```

**Fix.** `page` is capped at 100,000 (422 above that). The metric route maps `OverflowError` to
400 alongside `TypeError`/`ValueError` and returns a generic
`invalid parameters for metric <name>`. The fix is in `app/`, so the metric layer was not changed.

**Proof.** `test_sr3_huge_page_is_rejected_not_500` (3 cases),
`test_sr3_overflow_in_metric_is_400`, `test_sr3_bad_param_errors_do_not_echo_internals`. All failed
before the fix and pass after. Re-probe on the real warehouse: all four metric cases return 400 with
the generic message, and the huge page returns 422.

**Why Low.** It needs a valid login, and it exposes no data. It is noise in the error logs, and
error text that helps someone map the code.

## SR-4: API schema published to anonymous users (Low)

**What.** `/docs`, `/redoc` and `/openapi.json` were served to anyone in every environment. That
publishes every route, parameter and response shape without authentication.

**Evidence** (before fix, `NB_ENV=prod`): `docs: 200 openapi: 200 redoc: 200`.

**Fix.** Enabled only when `NB_ENV=dev`.

**Proof.** `test_sr4_api_docs_hidden_outside_dev` (3 paths) failed before the fix and passes after.
`test_sr4_api_docs_available_in_dev` still passes. Re-probe in prod: `[404, 404, 404]`.

---

## Checked and found sound (no finding)

These are recorded so the review shows what was ruled out, not only what was found.

| Probe | Result |
|---|---|
| SQL injection through metric params (`stage`, `department`, dates, `month`) | Every value is a bound `?` parameter. The only f-string SQL piece is `Scope.sql_filter`, built server-side from integers. |
| `**params` reaching unintended keyword arguments | Metric functions take only named arguments, and an unknown name is a `TypeError` → 400. `scope` and `con` are positional and also on the denylist, so they can't be overridden. |
| Login timing, known vs unknown email | Median 0.248s vs 0.240s over 8 tries each. bcrypt runs once on both paths. |
| Candidate PII through metric breakdowns | Breakdowns are by department, stage or period only. Of 560 candidates' names, emails and phones, **0** appear in any metric response for a scoped recruiter. |
| Scope bypass, token forgery, orphan visibility | Covered by 46 tests; see `docs/ACCESS_CONTROL.md`, including the four deliberate breakages. |
| `page=0`, `page=-1`, `page_size=0`, `page_size=101` | 422 |
| CORS | No CORS middleware, so browsers block cross-origin reads. The frontend is same-origin. |
| CSP | `default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'`. The frontend has no inline script or style, and the browser QA pass recorded no violations. |

## Not done, and why

- **Dependency audit.** `pip-audit` isn't installed and the review ran offline. Installed versions:
  fastapi 0.162.0, PyJWT 2.15.1, bcrypt 5.0.0, duckdb 2.0.0. Recommend `pip-audit -r
  requirements.txt` in CI, and pinning `bcrypt>=5` so that SR-2's truncation behaviour can't
  return through a fresh install.
- **Token revocation.** Signing out clears the token in the browser, but the token stays valid
  until `exp` (60 min). This is an accepted design point, not fixed: role and scope are re-read on
  every request, so a revoked user or a moved requisition takes effect immediately. Only "still
  signed in" outlives sign-out. A `jti` denylist would close it, but that adds a claim the contract
  rules out.
- **Shared demo password.** This is by design for the take-home, and it is what makes SR-1 High.
  Real deployments need per-user credentials or SSO.
