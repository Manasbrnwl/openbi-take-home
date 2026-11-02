"""THE metric layer. Every business metric is defined here, once.

The API calls `compute()`; the frontend renders what the API returns. If a definition changes
(e.g. time-to-hire starts from first Screen instead of application), this file is the only
file that changes.

Shared rules applied to every metric:
- Orphans (applications whose req_id is not a known requisition) are excluded. Only the
  candidate-pool count includes people regardless of applications — see `unique_people`.
- Access scope is applied in SQL via `Scope.sql_filter` on `req_key`.
- Values are returned ready to display in the stated unit; consumers do no arithmetic.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from metrics.scope import Scope

FUNNEL = ["Applied", "Screen", "Interview", "Offer", "Hired"]

METRICS: dict[str, dict] = {}


def metric(name: str, label: str, unit: str, description: str):
    def register(fn: Callable):
        METRICS[name] = {"fn": fn, "label": label, "unit": unit, "description": description}
        return fn

    return register


def _result(name: str, value, breakdown=None, **params) -> dict:
    m = METRICS[name]
    return {"metric": name, "label": m["label"], "unit": m["unit"], "value": value,
            "breakdown": breakdown, "params": {k: str(v) for k, v in params.items()}}


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _rows(con, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# --------------------------------------------------------------------------- definitions


@metric("unique_people", "People in candidate pool", "count",
        "Distinct people (deduplicated on phone), not candidate records. Admin: whole pool. "
        "Scoped users: people with at least one application on a requisition they can see.")
def unique_people(con, scope: Scope) -> dict:
    if scope.req_keys is None:
        v = con.execute("SELECT count(*) FROM gold.dim_candidate").fetchall()[0][0]
    else:
        f, p = scope.sql_filter("req_key")
        v = con.execute(f"SELECT count(DISTINCT candidate_key) FROM gold.fact_application "
                        f"WHERE NOT is_orphan AND {f}", p).fetchall()[0][0]
    return _result("unique_people", v)


@metric("applications_at_stage_asof", "Applications at stage, as at date", "count",
        "Applications whose stage at the close of `as_of` (23:59:59) was `stage`, from stage history.")
def applications_at_stage_asof(con, scope: Scope, stage: str = "Offer", as_of: str = "2026-03-31") -> dict:
    cutoff = _d(as_of) + timedelta(days=1)  # close of day = start of next day
    f, p = scope.sql_filter("a.req_key")
    rows = _rows(con, f"""
        SELECT r.department, count(*) AS applications
        FROM gold.fact_stage_history h
        JOIN gold.fact_application a USING (application_key)
        JOIN gold.dim_requisition r USING (req_key)
        WHERE NOT a.is_orphan AND h.stage = ?
          AND h.valid_from < ? AND (h.valid_to IS NULL OR h.valid_to >= ?) AND {f}
        GROUP BY 1 ORDER BY 1""", [stage, cutoff, cutoff, *p])
    return _result("applications_at_stage_asof", sum(r["applications"] for r in rows), rows,
                   stage=stage, as_of=as_of)


@metric("time_to_hire_median_days", "Median time to hire", "days",
        "Median of calendar days from application submitted to entering Hired, for hires dated "
        "within [start, end].")
def time_to_hire_median_days(con, scope: Scope, start: str = "2026-01-01", end: str = "2026-06-30") -> dict:
    f, p = scope.sql_filter("a.req_key")
    base = f"""FROM gold.fact_application a JOIN gold.dim_requisition r USING (req_key)
        WHERE NOT a.is_orphan AND a.hired_at >= ? AND a.hired_at < ? AND {f}"""
    args = [_d(start), _d(end) + timedelta(days=1), *p]
    days = "date_diff('day', CAST(a.applied_at AS DATE), CAST(a.hired_at AS DATE))"
    total = con.execute(f"SELECT median({days}), count(*) {base}", args).fetchall()[0]
    rows = _rows(con, f"SELECT r.department, median({days}) AS median_days, count(*) AS hires "
                      f"{base} GROUP BY 1 ORDER BY 1", args)
    return _result("time_to_hire_median_days", total[0], rows, start=start, end=end, hires=total[1])


@metric("offer_acceptance_rate", "Offer acceptance rate", "percent",
        "accepted / (accepted + declined) x 100, by offer status. Open offers excluded "
        "(their decided_at is populated in the source and is not a decision). Two decimals.")
def offer_acceptance_rate(con, scope: Scope, start: str | None = None, end: str | None = None) -> dict:
    f, p = scope.sql_filter("o.req_key")
    where, args = [f"NOT o.is_orphan", f], list(p)
    if start:
        where.append("o.offered_at >= ?"); args.append(_d(start))
    if end:
        where.append("o.offered_at <= ?"); args.append(_d(end))
    sql = f"""SELECT {{grp}} count(*) FILTER (o.status = 'accepted') AS accepted,
                     count(*) FILTER (o.status = 'declined') AS declined,
                     round(100.0 * count(*) FILTER (o.status = 'accepted')
                           / nullif(count(*) FILTER (o.status IN ('accepted', 'declined')), 0), 2) AS rate
              FROM gold.fact_offer o JOIN gold.dim_requisition r USING (req_key)
              WHERE {' AND '.join(where)} {{tail}}"""
    total = _rows(con, sql.format(grp="", tail=""), args)[0]
    rows = _rows(con, sql.format(grp="r.department,", tail="GROUP BY 1 ORDER BY 1"), args)
    return _result("offer_acceptance_rate", total["rate"], rows, start=start, end=end,
                   accepted=total["accepted"], declined=total["declined"])


@metric("offered_salary_total", "Total annual offered salary", "INR",
        "Sum of annual offered salary (INR, x100 entry errors corrected) for all offers of any "
        "status, by the requisition's department.")
def offered_salary_total(con, scope: Scope, department: str | None = None) -> dict:
    f, p = scope.sql_filter("o.req_key")
    rows = _rows(con, f"""
        SELECT r.department, sum(o.annual_salary_inr) AS total_inr, count(*) AS offers
        FROM gold.fact_offer o JOIN gold.dim_requisition r USING (req_key)
        WHERE NOT o.is_orphan AND {f} GROUP BY 1 ORDER BY 1""", p)
    if department:
        rows = [r for r in rows if r["department"] == department]
    return _result("offered_salary_total", int(sum(r["total_inr"] for r in rows)), rows,
                   department=department)


@metric("stage_conversion", "Stage conversion", "percent",
        "For each funnel stage, applications that ever reached it, and the % of those reaching "
        "the previous stage that went on to reach it. Applications dated within [start, end].")
def stage_conversion(con, scope: Scope, start: str | None = None, end: str | None = None) -> dict:
    f, p = scope.sql_filter("a.req_key")
    where, args = ["NOT a.is_orphan", f], list(p)
    if start:
        where.append("a.applied_at >= ?"); args.append(_d(start))
    if end:
        where.append("a.applied_at < ?"); args.append(_d(end) + timedelta(days=1))
    reached = {r["stage"]: r["n"] for r in _rows(con, f"""
        SELECT h.stage, count(DISTINCT h.application_key) AS n
        FROM gold.fact_stage_history h JOIN gold.fact_application a USING (application_key)
        WHERE {' AND '.join(where)} GROUP BY 1""", args)}
    rows, prev = [], None
    for s in FUNNEL:
        n = reached.get(s, 0)
        rows.append({"stage": s, "reached": n,
                     "conversion_from_previous": None if prev is None else
                     (round(100.0 * n / prev, 2) if prev else None)})
        prev = n
    overall = round(100.0 * reached.get("Hired", 0) / reached["Applied"], 2) if reached.get("Applied") else None
    return _result("stage_conversion", overall, rows, start=start, end=end)


@metric("applications_received_mom", "Applications received, month over month", "count",
        "Applications submitted in calendar month `month` vs the previous month: count, absolute "
        "and % change.")
def applications_received_mom(con, scope: Scope, month: str = "2026-06") -> dict:
    y, m = map(int, month.split("-"))
    cur_start = date(y, m, 1)
    prev_start = (cur_start - timedelta(days=1)).replace(day=1)
    next_start = (cur_start + timedelta(days=32)).replace(day=1)
    f, p = scope.sql_filter("a.req_key")
    r = _rows(con, f"""
        SELECT count(*) FILTER (a.applied_at >= ? AND a.applied_at < ?) AS current,
               count(*) FILTER (a.applied_at >= ? AND a.applied_at < ?) AS previous
        FROM gold.fact_application a WHERE NOT a.is_orphan AND {f}""",
        [cur_start, next_start, prev_start, cur_start, *p])[0]
    change = r["current"] - r["previous"]
    pct = round(100.0 * change / r["previous"], 2) if r["previous"] else None
    breakdown = [{"period": prev_start.strftime("%Y-%m"), "applications": r["previous"]},
                 {"period": month, "applications": r["current"]}]
    res = _result("applications_received_mom", r["current"], breakdown, month=month)
    res.update(previous=r["previous"], change=change, change_percent=pct)
    return res


# --------------------------------------------------------------------------- public API


def list_metrics() -> list[dict]:
    return [{"name": k, "label": v["label"], "unit": v["unit"], "description": v["description"]}
            for k, v in METRICS.items()]


def compute(con, name: str, scope: Scope, **params) -> dict:
    if name not in METRICS:
        raise KeyError(name)
    return METRICS[name]["fn"](con, scope, **params)
