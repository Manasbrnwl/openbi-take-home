# Estimate vs actual

Estimates were written before any code (see `docs/plans/01-initial-plan.md`). Actuals are
wall-clock time, read from commit times in `git log` and the session timeline. Work started at
about 23:40 on 2 Nov and the app was live at about 01:10 on 3 Nov.

Two sessions ran at the same time, so some rows overlap. The rows add up to more than the real
elapsed time, which was about 1.5 hours.

| # | Section | Estimate (h) | Actual (h) |
|---|---|---|---|
| 0 | Setup and planning: repo, CLAUDE.md, work list, estimates | 0.5 | 0.3 |
| 1–3 | Bronze, Silver, Gold, including the data checks behind them | 6.0 | 0.4 |
| 4 | Reconciliation note | 1.5 | 0.1 |
| 5 | Metric layer | 1.5 | 0.1 |
| 6 | API, login, access control and tests (session B, in parallel) | 2.5 | 0.2 |
| 7 | Frontend, checked in a real browser (session B) | 1.0 | 0.2 |
| 8 | Deployment: Dockerfile, GitHub, Render, live checks | 1.0 | 0.7 |
| 9 | Worklog, estimates, README | 1.0 | 0.3 |
| — | Extension C, security review (session B) | 0–1 | 0.2 |
|   | **Total** | **15.0** | **≈1.5 elapsed** |

## Where I was most wrong

I estimated as if I'd be typing the code myself. With two agents running at once, building took
minutes, and the real time went on reading and checking what they produced.

Deployment was the only section that came close to its estimate. The time went on things outside
the code: no SSH key for the GitHub push, Docker not running on my machine, and setting up Render.
