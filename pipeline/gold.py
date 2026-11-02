"""Gold: star schema. Grain of each table is stated in its docstring line and in docs/MODEL.md.

Surrogate keys are integers assigned by ordering on the natural key. Silver and Gold are full
rebuilds, so keys are stable across re-runs for unchanged data. (For incremental loads we'd
persist a natural-key -> surrogate-key map table; noted in README "left out".)
"""
from __future__ import annotations

UNKNOWN_REQ_KEY = -1

FUNNEL = ["Applied", "Screen", "Interview", "Offer", "Hired"]


def build(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS gold")

    # dim_date — grain: one row per calendar day covering the ATS lifetime.
    con.execute("""
    CREATE OR REPLACE TABLE gold.dim_date AS
    SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key, CAST(d AS DATE) AS date,
           year(d) AS year, quarter(d) AS quarter, month(d) AS month,
           strftime(d, '%Y-%m') AS year_month, strftime(d, '%b') AS month_name,
           isodow(d) AS iso_dow
    FROM generate_series(DATE '2025-09-01', DATE '2027-12-31', INTERVAL 1 DAY) t(d)""")

    # dim_user — grain: one row per ATS user.
    con.execute("""
    CREATE OR REPLACE TABLE gold.dim_user AS
    SELECT row_number() OVER (ORDER BY user_id) AS user_key, user_id, name, email, role, department
    FROM silver.users""")

    # dim_requisition — grain: one row per requisition, plus the -1 'Unknown requisition' member
    # that orphaned applications point at (so they are kept, not dropped, and are filterable).
    con.execute(f"""
    CREATE OR REPLACE TABLE gold.dim_requisition AS
    SELECT row_number() OVER (ORDER BY r.req_id) AS req_key, r.req_id, r.title, r.department,
           r.location, r.status, r.headcount, r.opened_date, r.closed_date,
           r.hiring_manager_id, r.recruiter_id,
           hm.user_key AS hiring_manager_user_key, rc.user_key AS recruiter_user_key
    FROM silver.requisitions r
    LEFT JOIN gold.dim_user hm ON hm.user_id = r.hiring_manager_id
    LEFT JOIN gold.dim_user rc ON rc.user_id = r.recruiter_id
    UNION ALL
    SELECT {UNKNOWN_REQ_KEY}, 'UNKNOWN', 'Unknown requisition', 'Unknown', NULL, NULL, NULL,
           NULL, NULL, NULL, NULL, NULL, NULL""")

    # dim_candidate — grain: one row per PERSON (deduplicated). Attributes from the survivor
    # (earliest) record. bridge_candidate_record maps every source candidate_id to its person.
    con.execute("""
    CREATE OR REPLACE TABLE gold.dim_candidate AS
    SELECT row_number() OVER (ORDER BY c.person_id) AS candidate_key, c.person_id,
           c.full_name, c.email, c.phone, c.source, c.created_at AS first_seen_at,
           c.records_for_person AS record_count
    FROM silver.candidates c WHERE c.candidate_id = c.person_id""")

    con.execute("""
    CREATE OR REPLACE TABLE gold.bridge_candidate_record AS
    SELECT c.candidate_id, d.candidate_key, c.candidate_id <> c.person_id AS is_duplicate_record,
           c.email AS record_email, c.source AS record_source, c.created_at AS record_created_at
    FROM silver.candidates c JOIN gold.dim_candidate d ON d.person_id = c.person_id""")

    # fact_stage_history — grain: one row per period an application spent in one stage
    # (from the event that entered it until the next event). valid_to NULL = still there.
    # Point-in-time query: valid_from < t AND (valid_to IS NULL OR valid_to >= t), t = end of day.
    con.execute("""
    CREATE OR REPLACE TABLE gold.fact_stage_history AS
    SELECT row_number() OVER (ORDER BY e.application_id, e.event_seq) AS stage_period_key,
           e.event_id, e.application_id, e.to_stage AS stage, e.from_stage AS previous_stage,
           e.changed_at AS valid_from,
           lead(e.changed_at) OVER w AS valid_to,
           lead(e.changed_at) OVER w IS NULL AS is_current,
           row_number() OVER w AS stage_seq,
           CAST(strftime(e.changed_at, '%Y%m%d') AS INTEGER) AS entered_date_key,
           u.user_key AS changed_by_user_key
    FROM silver.stage_events e
    LEFT JOIN gold.dim_user u ON u.user_id = e.changed_by
    WINDOW w AS (PARTITION BY e.application_id ORDER BY e.event_seq)""")

    # fact_application — grain: one row per application (a person applying to one requisition
    # on one date). current_stage is DERIVED from history; the source column is kept for audit.
    con.execute(f"""
    CREATE OR REPLACE TABLE gold.fact_application AS
    WITH cur AS (SELECT application_id, stage FROM gold.fact_stage_history WHERE is_current),
    hired AS (SELECT application_id, min(valid_from) AS hired_at FROM gold.fact_stage_history
              WHERE stage = 'Hired' GROUP BY 1)
    SELECT row_number() OVER (ORDER BY a.application_id) AS application_key, a.application_id,
           b.candidate_key, a.candidate_id AS source_candidate_id,
           coalesce(r.req_key, {UNKNOWN_REQ_KEY}) AS req_key, a.req_id,
           a.applied_at, CAST(strftime(a.applied_at, '%Y%m%d') AS INTEGER) AS applied_date_key,
           cur.stage AS current_stage, h.hired_at,
           a.source_current_stage, coalesce(cur.stage <> a.source_current_stage, TRUE) AS source_stage_stale,
           a.is_orphan
    FROM silver.applications a
    JOIN gold.bridge_candidate_record b ON b.candidate_id = a.candidate_id
    LEFT JOIN gold.dim_requisition r ON r.req_id = a.req_id AND r.req_key <> {UNKNOWN_REQ_KEY}
    LEFT JOIN cur ON cur.application_id = a.application_id
    LEFT JOIN hired h ON h.application_id = a.application_id""")

    con.execute("""
    ALTER TABLE gold.fact_stage_history ADD COLUMN application_key BIGINT;
    UPDATE gold.fact_stage_history s SET application_key = f.application_key
    FROM gold.fact_application f WHERE f.application_id = s.application_id;""")

    # fact_offer — grain: one row per offer extended against an application.
    # Department comes from the requisition (conformed), not the offer sheet's own column.
    con.execute("""
    CREATE OR REPLACE TABLE gold.fact_offer AS
    SELECT row_number() OVER (ORDER BY o.offer_id) AS offer_key, o.offer_id,
           f.application_key, f.candidate_key, f.req_key, f.is_orphan,
           o.offered_at, CAST(strftime(o.offered_at, '%Y%m%d') AS INTEGER) AS offered_date_key,
           o.decided_at, o.status, o.annual_salary_inr, o.currency,
           o.annual_salary_raw, o.salary_corrected
    FROM silver.offers o JOIN gold.fact_application f ON f.application_id = o.application_id""")

    # fact_interview — grain: one row per scheduled interview.
    # 9 interviews reference application_ids that do not exist (A9xxxx). Kept, not dropped:
    # application_key NULL, req_key -1, is_orphan TRUE.
    con.execute(f"""
    CREATE OR REPLACE TABLE gold.fact_interview AS
    SELECT row_number() OVER (ORDER BY i.interview_id) AS interview_key, i.interview_id,
           i.application_id AS source_application_id, f.application_key,
           coalesce(f.req_key, {UNKNOWN_REQ_KEY}) AS req_key, coalesce(f.is_orphan, TRUE) AS is_orphan,
           f.application_key IS NULL AS application_missing,
           u.user_key AS interviewer_user_key,
           i.scheduled_at, CAST(strftime(i.scheduled_at, '%Y%m%d') AS INTEGER) AS scheduled_date_key,
           i.interview_type, i.outcome, i.score
    FROM silver.interviews i
    LEFT JOIN gold.fact_application f ON f.application_id = i.application_id
    LEFT JOIN gold.dim_user u ON u.user_id = i.interviewer_id""")
