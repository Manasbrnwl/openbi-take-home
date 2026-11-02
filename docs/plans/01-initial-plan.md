# Plan 01 — initial work breakdown (written before any code)

Prompt given to the agent: *"do not start any work first list down all the work what have to
done and which data have to be used and where to use"*. This is the breakdown that came back
and that I approved, with the data profiling it was based on.

## Data profiling done before planning

| File | Rows | Issue spotted at planning time |
|---|---|---|
| candidates.csv | 601 | 574 distinct emails, 41 shared phones, 101 repeated names → people appear >1×; target 560 |
| applications.csv | 1,450 | 23 reference `REQ-2xxx` ids not in requisitions.json; `current_stage` untrustworthy |
| stage_events.csv | 4,774 | `event_seq` order vs `changed_at` order looked inconsistent for 60 applications (later found to be timestamp ties — see worklog) |
| requisitions.json | 26 | clean; master list of valid reqs |
| users.json | 14 | 4 recruiters, 8 HMs, 2 admins |
| interviews.json | 1,284 | not used by any control |
| offers.xlsx | 421 | salaries 100× too large on some rows; every open offer has a `decided_at` |

## Build order and estimates (hours)

| # | Section | Est. |
|---|---|---|
| 0 | Setup: repo, CLAUDE.md, plan, estimates | 0.5 |
| 1 | Bronze: land 7 files + lineage, idempotent | 1.5 |
| 2 | Silver: types, trim, salary fix, person dedupe, orphan flag, event order | 2.5 |
| 3 | Gold: dims (candidate=person, req, user, date), facts (application, stage history, offer, interview), grain + SKs | 2.0 |
| 4 | Reconciliation note | 1.5 |
| 5 | Metric layer (one module) | 1.5 |
| 6 | API + JWT auth + server-side row scope + bypass tests | 2.5 |
| 7 | Frontend (thin) | 1.0 |
| 8 | Deployment (free host) + "before real users" note | 1.0 |
| 9 | Worklog, estimate-vs-actual, README | 1.0 |
| — | Extension (only if core done): C security review or A NL Q&A | 0–1 |
|   | **Total** | **15.0** |

## Deliberately dropped at planning time
CRUD screens, visual polish, more than one extension, heavyweight infra.
