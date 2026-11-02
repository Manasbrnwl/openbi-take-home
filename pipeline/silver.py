"""Silver: typed, cleaned, deduplicated, conformed. Rebuilt in full from the latest Bronze batch
of each source on every run (CREATE OR REPLACE), so it is deterministic and idempotent.

Every cleaning rule below is a decision recorded in docs/RECONCILIATION.md.
"""
from __future__ import annotations

# Values at or above this are treated as recorded x100 (paise, or a units slip). The legitimate
# offer bands in the extract run 900,000-3,000,000 INR; every inflated value is exactly 100x one of
# those bands. 1 crore (10,000,000) sits far above any genuine band and far below any inflated one.
SALARY_X100_THRESHOLD = 10_000_000


def _latest(source: str) -> str:
    return f"""(SELECT * FROM bronze.{source} WHERE _batch_id = (
        SELECT batch_id FROM bronze._load_log WHERE source = '{source}'
        ORDER BY loaded_at DESC LIMIT 1))"""


def build(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")

    con.execute(f"""
    CREATE OR REPLACE TABLE silver.users AS
    SELECT trim(user_id) AS user_id, trim(name) AS name, lower(trim(email)) AS email,
           lower(trim(role)) AS role, nullif(trim(department), '') AS department,
           _batch_id
    FROM {_latest('users')}""")

    con.execute(f"""
    CREATE OR REPLACE TABLE silver.requisitions AS
    SELECT trim(req_id) AS req_id, trim(title) AS title, trim(department) AS department,
           trim(location) AS location, trim(hiring_manager_id) AS hiring_manager_id,
           trim(recruiter_id) AS recruiter_id, CAST(headcount AS INTEGER) AS headcount,
           CAST(opened_date AS DATE) AS opened_date, CAST(nullif(closed_date, 'None') AS DATE) AS closed_date,
           lower(trim(status)) AS status, _batch_id
    FROM {_latest('requisitions')}""")

    # Candidates. Identity = normalised phone. Email is NOT used: 24 emails are shared by
    # different people (same common name, different phone, no other overlap). The 41 phone
    # collisions are true duplicates: later record, mangled name casing, digit-suffixed email,
    # identical time-of-day on created_at. Survivor = earliest-created record in the group.
    con.execute(f"""
    CREATE OR REPLACE TABLE silver.candidates AS
    WITH typed AS (
        SELECT trim(candidate_id) AS candidate_id,
               regexp_replace(trim(full_name), '\\s+', ' ', 'g') AS full_name_raw,
               lower(trim(email)) AS email,
               regexp_replace(phone, '[^0-9]', '', 'g') AS phone_digits,
               trim(source) AS source,
               CAST(created_at AS TIMESTAMP) AS created_at,
               _batch_id
        FROM {_latest('candidates')}
    )
    SELECT candidate_id,
           -- display name: collapse whitespace, title-case each word
           array_to_string(list_transform(string_split(full_name_raw, ' '),
               lambda w: upper(w[1]) || lower(w[2:])), ' ') AS full_name,
           email, '+' || phone_digits AS phone, phone_digits, source, created_at,
           first_value(candidate_id) OVER (PARTITION BY phone_digits ORDER BY created_at, candidate_id) AS person_id,
           count(*) OVER (PARTITION BY phone_digits) AS records_for_person,
           _batch_id
    FROM typed""")

    con.execute(f"""
    CREATE OR REPLACE TABLE silver.applications AS
    SELECT trim(a.application_id) AS application_id, trim(a.candidate_id) AS candidate_id,
           c.person_id, trim(a.req_id) AS req_id,
           CAST(a.applied_at AS TIMESTAMP) AS applied_at,
           trim(a.current_stage) AS source_current_stage,   -- untrusted; audit only
           lower(a.is_active) = 'true' AS source_is_active,
           r.req_id IS NULL AS is_orphan,                    -- req_id not in requisitions
           a._batch_id
    FROM {_latest('applications')} a
    LEFT JOIN silver.candidates c ON c.candidate_id = trim(a.candidate_id)
    LEFT JOIN silver.requisitions r ON r.req_id = trim(a.req_id)""")

    # Stage events. Order of truth = event_seq. 60 pairs of events share a changed_at
    # timestamp (same-instant transitions); event_seq orders them and the from->to chain is
    # unbroken in event_seq order, which confirms it.
    con.execute(f"""
    CREATE OR REPLACE TABLE silver.stage_events AS
    SELECT trim(event_id) AS event_id, trim(application_id) AS application_id,
           nullif(trim(from_stage), '') AS from_stage, trim(to_stage) AS to_stage,
           CAST(changed_at AS TIMESTAMP) AS changed_at, CAST(event_seq AS INTEGER) AS event_seq,
           trim(changed_by) AS changed_by, _batch_id
    FROM {_latest('stage_events')}
    QUALIFY row_number() OVER (PARTITION BY trim(event_id) ORDER BY _source_row) = 1""")

    con.execute(f"""
    CREATE OR REPLACE TABLE silver.interviews AS
    SELECT trim(interview_id) AS interview_id, trim(application_id) AS application_id,
           CAST(scheduled_at AS TIMESTAMP) AS scheduled_at, trim(interviewer_id) AS interviewer_id,
           trim(type) AS interview_type, lower(trim(outcome)) AS outcome,
           TRY_CAST(score AS INTEGER) AS score, _batch_id
    FROM {_latest('interviews')}
    QUALIFY row_number() OVER (PARTITION BY trim(interview_id) ORDER BY _source_row) = 1""")

    # Offers. (1) salaries >= 1 crore are 100x inflated -> divide, keep raw + flag.
    # (2) decided_at is populated on 'open' offers; it is not a decision, so null it for open.
    con.execute(f"""
    CREATE OR REPLACE TABLE silver.offers AS
    WITH typed AS (
        SELECT trim(offer_id) AS offer_id, trim(application_id) AS application_id,
               trim(department) AS source_department,
               CAST(offered_at AS DATE) AS offered_at,
               CAST(CAST(annual_salary AS DOUBLE) AS BIGINT) AS annual_salary_raw,
               upper(trim(currency)) AS currency, lower(trim(status)) AS status,
               CAST(decided_at AS DATE) AS decided_at_raw, _batch_id
        FROM {_latest('offers')}
    )
    SELECT offer_id, application_id, source_department, offered_at, currency, status,
           annual_salary_raw,
           annual_salary_raw >= {SALARY_X100_THRESHOLD} AS salary_corrected,
           CASE WHEN annual_salary_raw >= {SALARY_X100_THRESHOLD} THEN annual_salary_raw // 100
                ELSE annual_salary_raw END AS annual_salary_inr,
           decided_at_raw,
           CASE WHEN status IN ('accepted', 'declined') THEN decided_at_raw END AS decided_at,
           _batch_id
    FROM typed
    QUALIFY row_number() OVER (PARTITION BY offer_id ORDER BY offered_at) = 1""")
