# CLAUDE.md — agent context for this repository

Northbeam ATS analytics: medallion pipeline (DuckDB) → Gold star schema → one metric layer →
FastAPI → thin frontend. Take-home for OpenBI. Read the candidate brief (provided by OpenBI, kept out of this public repo) and
`docs/CONTRACT.md` before changing anything.

## Non-negotiables

1. **Metrics are defined once, in `metrics/definitions.py`.** Nowhere else computes a metric.
   `app/` and `frontend/` never do arithmetic on metric values. If you need a new number,
   add a definition there; do not inline SQL for it in a route.
2. **Stage is history.** Point-in-time questions read `gold.fact_stage_history`
   (`valid_from <= t < valid_to`). `applications.current_stage` from the source is untrusted
   and only kept in Silver for reconciliation.
3. **Access scope is resolved server-side from the verified token's user id** (`app/security.py`)
   and applied in SQL. Never trust a user id, role, or req id from the request for authorization.
4. **Pipeline is idempotent.** Re-running `python -m pipeline.run` must yield identical row counts.
5. **Do not "fix" a control total by tuning logic until it matches.** If a number doesn't tie,
   the finding goes in `docs/RECONCILIATION.md` with the cause.
6. Raw data in `northbeam_ats_pack/` is read-only.

## Data decisions already made (do not silently change)

- Person identity = normalised phone (digits only). Email is NOT an identity key: 24 email
  collisions are different people (same common name, different phones). See RECONCILIATION.md.
- Applications whose `req_id` is not in requisitions.json → `req_key = -1`, `is_orphan = true`,
  excluded from all controls and visible only to admins.
- Salaries recorded ×100 (values ≥ 10,000,000 that are exact multiples of 100 of a valid band) are
  divided by 100 in Silver, with `salary_corrected = true` kept for audit.
- Offer acceptance uses `status in ('accepted','declined')`; `decided_at` is populated on open
  offers and is not a decision signal.

## Layout

```
pipeline/   bronze.py silver.py gold.py run.py      (session A)
metrics/    __init__.py definitions.py               (session A)
app/        FastAPI, auth, security scope             (session B)
frontend/   static page consuming the API             (session B)
tests/      pytest: controls, idempotency, access control
docs/       CONTRACT, RECONCILIATION, WORKLOG, ESTIMATES, plans/
```

## Commands

```
uv venv .venv --python 3.12 && uv pip install --python .venv -r requirements.txt
.venv/Scripts/python -m pipeline.run         # build warehouse/northbeam.duckdb
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## Working rules for agents

- Two agent sessions work in this repo concurrently. Stage only your own paths
  (`git add <paths>`, never `git add -A`) and make small commits with clear messages.
- Windows host: use `.venv/Scripts/python`.
