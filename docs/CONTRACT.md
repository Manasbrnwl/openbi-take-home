# Component contract — Gold layer ↔ metric layer ↔ API ↔ frontend

This file is the interface between the data layer (session A, `pipeline/`, `metrics/`)
and the application (session B, `app/`, `frontend/`). Change it only by agreement.

## Storage

- One DuckDB file: `warehouse/northbeam.duckdb` (gitignored; built by `python -m pipeline.run`).
- Schemas: `bronze`, `silver`, `gold`. The API opens it **read-only** and touches only `gold.*`
  through the metric layer and the scoped query helpers below.

## Gold tables (columns the app may rely on)

| Table | Grain (one row per…) | Key columns |
|---|---|---|
| `gold.dim_user` | ATS user | `user_key`, `user_id`, `name`, `email`, `role` (`recruiter`/`hiring_manager`/`admin`), `department` |
| `gold.dim_requisition` | requisition (+ one `req_key = -1` "Unknown requisition" member) | `req_key`, `req_id`, `title`, `department`, `location`, `status`, `headcount`, `opened_date`, `closed_date`, `hiring_manager_id`, `recruiter_id` |
| `gold.dim_candidate` | **person** (deduplicated) | `candidate_key`, `person_id`, `full_name`, `email`, `phone`, `source`, `record_count` |
| `gold.fact_application` | application | `application_key`, `application_id`, `candidate_key`, `req_key`, `req_id`, `applied_at`, `current_stage` (derived from history), `is_orphan` |
| `gold.fact_stage_history` | period an application spent in one stage | `application_key`, `stage`, `valid_from`, `valid_to` (NULL = current), `stage_seq` |
| `gold.fact_offer` | offer | `offer_key`, `offer_id`, `application_key`, `req_key`, `offered_at`, `annual_salary_inr`, `status`, `decided_at` |
| `gold.fact_interview` | interview | `interview_key`, `application_key`, `interviewer_user_key`, `scheduled_at`, `type`, `outcome`, `score` |

## Access scope — the one rule

```
admin           -> all requisitions (req_key >= 0) plus orphans
hiring_manager  -> dim_requisition.hiring_manager_id = <their user_id>
recruiter       -> dim_requisition.recruiter_id      = <their user_id>
```

The scope is derived **only** from the authenticated user's id in the verified token, looked up in
`gold.dim_user` / `gold.dim_requisition`. Never from a query param, header, or body field. A
requested `req_id` outside scope returns **404** (not 403, so existence isn't leaked).

Scope is represented as `Scope(user_id: str, role: str, req_keys: frozenset[int] | None)`;
`None` means unrestricted (admin). Every metric function and every list query takes a `Scope`
and applies it in SQL.

## Metric layer interface (`metrics/`, owned by session A)

```python
from metrics import compute, list_metrics, Scope
list_metrics() -> list[dict]          # name, label, unit, description
compute(con, name: str, scope: Scope, **params) -> dict
# -> {"metric": name, "label": ..., "unit": "days"|"percent"|"count"|"INR",
#     "value": float|int|None, "breakdown": list[dict] | None, "params": {...}}
```

Metric names: `time_to_hire_median_days`, `offer_acceptance_rate`, `stage_conversion`,
`applications_received_mom` (period-over-period), plus the control-total metrics
`unique_people`, `applications_at_stage_asof`, `offered_salary_total`.

The API must return these dicts unchanged. **No arithmetic on metric values in `app/` or
`frontend/`** — not even a percentage format multiplication. Units are delivered ready to display.
