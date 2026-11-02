# How we know access control can't be bypassed

## The rule

| Role | Sees |
|---|---|
| admin | every requisition, plus orphan applications (`req_key = -1`) |
| hiring_manager | requisitions where `dim_requisition.hiring_manager_id` = their user id |
| recruiter | requisitions where `dim_requisition.recruiter_id` = their user id |

Any other role is denied (401). It never falls through to "everything".

## How it is enforced

1. **The token proves identity only.** `POST /auth/login` issues an HS256 JWT with exactly two
   claims, `sub` (user id) and `exp` (60 min). Role and requisitions are not in the token, so there
   is nothing in it to edit, and a role change takes effect on the next request.
2. **There is one place a `Scope` is built.** `app/security.py::build_scope` decodes the bearer
   token with the algorithm pinned to `HS256` and `sub`/`exp` required. It then looks up the user's
   role in `gold.dim_user` and their `req_key`s in `gold.dim_requisition`. The column it filters on
   comes from a fixed dict keyed by role, never from input. The function reads nothing else from the
   request: no query params, no other headers, no body.
3. **Scope is applied in SQL, not in Python.** Every data endpoint depends on `get_scope` and calls
   `Scope.sql_filter(column)`. Admin gets `TRUE`, everyone else gets `req_key IN (?, …)` with bound
   parameters, and an empty scope gets `FALSE`. Metric functions get the same `Scope` object.
   `/metrics/{name}` passes query params through to the metric, but drops `scope`, `user_id`,
   `role`, `req_keys`, `con`, `name` and `token` first.
4. **Out of scope looks the same as missing.** `/requisitions/{id}/applications` answers 404 with
   the same body for a requisition you don't own and one that doesn't exist.
5. **PII follows the rows.** Candidate email and phone are joined onto application rows that have
   already passed the scope filter. There is no endpoint that returns candidates directly.
6. **Startup refuses unsafe defaults.** Outside `NB_ENV=dev`/`test`, the app won't start without
   `NB_JWT_SECRET` (at least 32 bytes) and `NB_DEMO_PASSWORD`. In dev the secret is random per
   process, so no well-known secret exists. Login runs bcrypt for unknown emails too and returns the
   same message, so neither timing nor wording reveals which emails exist.

## The attacks the tests try

All through the HTTP layer with FastAPI's `TestClient`. Tests are in `tests/test_access_control.py`
(fixture warehouse) and `tests/test_access_real_warehouse.py` (real data, skipped if not built).

| Attack | Expected | Test |
|---|---|---|
| No token, or `Basic` auth, on every data endpoint | 401 | `test_every_data_endpoint_requires_auth` |
| Token signed with the wrong secret | 401 | `test_tampered_tokens_are_rejected[wrong_secret]` |
| `alg=none`, with and without a signature segment | 401 | `[alg_none]`, `[alg_none_with_sig]` |
| Correct secret but `HS512` | 401 | `[other_alg_hs512]` |
| Expired token; token with no `exp`; no `sub`; non-string `sub` | 401 | `[expired]`, `[no_exp]`, `[no_sub]`, `[non_string_sub]` |
| HM's genuine signature with the payload swapped to `sub=U013` (admin) | 401 | `[payload_swapped]` |
| Validly signed token for a user id not in `dim_user` | 401 | `[unknown_user]` |
| Validly signed token that also claims `role=admin` | role claim ignored | `test_role_claim_in_token_is_ignored` |
| `?user_id=U013`, `?role=admin`, `?req_keys=…`, `?scope=admin` | responses identical | `test_identity_params_and_headers_change_nothing` |
| `X-User-Id`, `X-Role`, `X-Forwarded-User` headers | responses identical | same |
| HM U005 opens another HM's requisition | 404, same as a missing req | `test_hm_cannot_open_another_hms_requisition`, `test_u005_cannot_open_other_hms_reqs` (all 23 real ones) |
| Recruiter sees only reqs where they're the recruiter | exact set | `test_recruiter_sees_exactly_reqs_where_they_are_recruiter`, `test_each_user_sees_exactly_their_reqs` (all 14 real users) |
| Metric values for an HM | differ from admin, only their reqs | `test_metric_values_are_scoped`, `test_hm_metrics_differ_from_admin_and_ignore_identity_params` (all 7 real metrics) |
| Any metric, present or future, gets the token's scope | spy on `compute` sees U005's scope | `test_metric_route_passes_server_built_scope_for_every_metric` |
| Orphan applications | admin only | `test_orphan_applications_visible_to_admin_only`, `test_orphans_never_reach_non_admins` |
| Another HM's candidates' email/phone | absent | `test_pii_only_on_entitled_rows` |
| Role with no scope rule (`auditor`) | 401, not everything | `test_unscopable_role_is_denied` |
| `page_size` over 100 | 422 | `test_page_size_is_capped` |

On the real warehouse, there is also a completeness check. The recruiters' visible applications
(1,427) plus the orphans (23) equal admin's total (1,450), and the same holds for the hiring
managers. So the scopes partition the data: nothing is double-counted and nothing falls between
roles.

## Proof the tests can fail

A test suite that passes is only evidence if it would fail when the code is wrong. We broke the app
four ways, one at a time, ran the 54 app tests, and restored the code each time.

| Deliberate breakage | Tests failed (of 54) |
|---|---|
| Non-admins get admin scope (`req_keys = None` for HM and recruiter) | 23 |
| JWT signature and expiry not verified (`verify_signature: False`) | 7 |
| Identity-like query params passed through to metric functions | 3 |
| Out-of-scope requisition returns 403 instead of 404 (leaks existence) | 12 |

The 7 in the second row are the token-forgery cases that depend on the signature or on `exp`.
Unknown user, missing `sub` and garbage tokens still fail at the user lookup, as they should.

## Known limits (deliberately out of scope for a take-home)

- No login rate limiting or lockout.
- No token revocation before `exp`. Role and scope are re-read on every request, so the window is
  "still authenticated", not "still privileged".
- Every demo user shares one password from `NB_DEMO_PASSWORD`. It is a demo credential store, not
  user management.
- The frontend keeps the token in `sessionStorage`. The CSP (`script-src 'self'`, no inline
  scripts) and `textContent`-only rendering are what keep XSS from reaching it.
