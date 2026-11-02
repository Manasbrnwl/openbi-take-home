"""Shared fixtures. `fixture_warehouse` builds a tiny Gold layer matching docs/CONTRACT.md so the
app and its access-control tests run before (and independently of) the real pipeline."""
from __future__ import annotations

import duckdb
import pytest

# Ownership in the fixture (mirrors the shape of the real data):
#   REQ-1001 hm U006 rec U001      REQ-1003 hm U005 rec U001
#   REQ-1004 hm U006 rec U002      REQ-1005 hm U005 rec U002
#   req_key -1 = Unknown requisition; 2 orphan applications point at REQ-9999 (not in requisitions)
USERS = [
    (1, "U001", "Naveen Malhotra", "naveen.malhotra@northbeam.example", "recruiter", None),
    (2, "U002", "Gaurav Khanna", "gaurav.khanna@northbeam.example", "recruiter", None),
    (5, "U005", "Uday Varma", "uday.varma@northbeam.example", "hiring_manager", "Engineering"),
    (6, "U006", "Harsh Agarwal", "harsh.agarwal@northbeam.example", "hiring_manager", "Data"),
    (13, "U013", "Admin One", "admin.one@northbeam.example", "admin", None),
    (99, "U099", "Odd Role", "odd.role@northbeam.example", "auditor", None),
]
REQS = [
    (-1, "UNKNOWN", "Unknown requisition", None, None, None, None, None, None, None, None),
    (1, "REQ-1001", "Financial Analyst", "Data", "Bengaluru", "open", 1, "2026-04-28", None, "U006", "U001"),
    (3, "REQ-1003", "Backend Engineer", "Engineering", "Gurgaon", "closed", 1, "2025-10-05", "2026-04-14", "U005", "U001"),
    (4, "REQ-1004", "Financial Analyst", "Finance", "Pune", "open", 1, "2026-04-10", None, "U006", "U002"),
    (5, "REQ-1005", "Solutions Engineer", "Engineering", "Pune", "open", 2, "2026-01-10", None, "U005", "U002"),
]
# (application_key, application_id, candidate_key, req_key, req_id, applied_at, current_stage, is_orphan)
APPS = [
    (1, "A00001", 1, 1, "REQ-1001", "2026-05-01 10:00:00", "Applied", False),
    (2, "A00002", 2, 1, "REQ-1001", "2026-05-02 10:00:00", "Screen", False),
    (3, "A00003", 3, 3, "REQ-1003", "2025-11-01 10:00:00", "Hired", False),
    (4, "A00004", 4, 3, "REQ-1003", "2025-11-03 10:00:00", "Rejected", False),
    (5, "A00005", 5, 3, "REQ-1003", "2025-11-05 10:00:00", "Offer", False),
    (6, "A00006", 6, 4, "REQ-1004", "2026-04-15 10:00:00", "Applied", False),
    (7, "A00007", 7, 5, "REQ-1005", "2026-02-01 10:00:00", "Interview", False),
    (8, "A00008", 1, 5, "REQ-1005", "2026-02-02 10:00:00", "Applied", False),
    (9, "A00009", 8, -1, "REQ-9999", "2026-03-01 10:00:00", "Applied", True),
    (10, "A00010", 9, -1, "REQ-9999", "2026-03-02 10:00:00", "Screen", True),
]
CANDIDATES = [
    (k, f"P{k:04d}", f"Candidate {k}", f"cand{k}@mail.example", f"9100000{k:03d}", "Referral", 1)
    for k in range(1, 10)
]

DDL = """
CREATE SCHEMA gold;
CREATE TABLE gold.dim_user (user_key INT, user_id VARCHAR, name VARCHAR, email VARCHAR, role VARCHAR, department VARCHAR);
CREATE TABLE gold.dim_requisition (req_key INT, req_id VARCHAR, title VARCHAR, department VARCHAR, location VARCHAR,
    status VARCHAR, headcount INT, opened_date DATE, closed_date DATE, hiring_manager_id VARCHAR, recruiter_id VARCHAR);
CREATE TABLE gold.dim_candidate (candidate_key INT, person_id VARCHAR, full_name VARCHAR, email VARCHAR, phone VARCHAR,
    source VARCHAR, record_count INT);
CREATE TABLE gold.fact_application (application_key INT, application_id VARCHAR, candidate_key INT, req_key INT,
    req_id VARCHAR, applied_at TIMESTAMP, current_stage VARCHAR, is_orphan BOOLEAN);
CREATE TABLE gold.fact_stage_history (application_key INT, stage VARCHAR, valid_from TIMESTAMP, valid_to TIMESTAMP, stage_seq INT);
CREATE TABLE gold.fact_offer (offer_key INT, offer_id VARCHAR, application_key INT, req_key INT, offered_at TIMESTAMP,
    annual_salary_inr BIGINT, status VARCHAR, decided_at TIMESTAMP);
CREATE TABLE gold.fact_interview (interview_key INT, application_key INT, interviewer_user_key INT, scheduled_at TIMESTAMP,
    type VARCHAR, outcome VARCHAR, score DOUBLE);
"""


def build_fixture_warehouse(path: str) -> None:
    con = duckdb.connect(path)
    con.execute(DDL)
    con.executemany("INSERT INTO gold.dim_user VALUES (?,?,?,?,?,?)", USERS)
    con.executemany("INSERT INTO gold.dim_requisition VALUES (?,?,?,?,?,?,?,?,?,?,?)", REQS)
    con.executemany("INSERT INTO gold.dim_candidate VALUES (?,?,?,?,?,?,?)", CANDIDATES)
    con.executemany("INSERT INTO gold.fact_application VALUES (?,?,?,?,?,?,?,?)", APPS)
    con.executemany(
        "INSERT INTO gold.fact_stage_history VALUES (?,?,?,NULL,1)",
        [(a[0], a[6], a[5]) for a in APPS],
    )
    con.executemany(
        "INSERT INTO gold.fact_offer VALUES (?,?,?,?,?,?,?,?)",
        [(1, "O001", 3, 3, "2025-12-01", 2400000, "accepted", "2025-12-05"),
         (2, "O002", 5, 3, "2025-12-10", 2200000, "pending", None)],
    )
    con.close()


@pytest.fixture(scope="session")
def fixture_warehouse(tmp_path_factory) -> str:
    path = str(tmp_path_factory.mktemp("wh") / "fixture.duckdb")
    build_fixture_warehouse(path)
    return path
