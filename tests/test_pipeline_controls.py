"""Control totals, idempotency and no-silent-drop checks. Builds a throwaway warehouse."""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import duckdb
import pytest

from metrics import Scope, compute
from pipeline.run import DEFAULT_SOURCE, run

ADMIN = Scope("U013", "admin", None)


@pytest.fixture(scope="module")
def wh(tmp_path_factory):
    path = tmp_path_factory.mktemp("wh") / "test.duckdb"
    first = run(DEFAULT_SOURCE, path)
    second = run(DEFAULT_SOURCE, path)  # re-run must be a no-op on row counts
    con = duckdb.connect(str(path), read_only=True)
    yield con, first, second
    con.close()


def test_rerun_does_not_duplicate(wh):
    _, first, second = wh
    assert first["counts"] == second["counts"]
    assert all(v.startswith("skipped") for v in second["landed"].values())


@pytest.mark.parametrize("silver,gold", [
    ("silver.applications", "gold.fact_application"),
    ("silver.stage_events", "gold.fact_stage_history"),
    ("silver.offers", "gold.fact_offer"),
    ("silver.interviews", "gold.fact_interview"),
])
def test_no_rows_silently_dropped(wh, silver, gold):
    con, *_ = wh
    s = con.execute(f"SELECT count(*) FROM {silver}").fetchall()[0][0]
    g = con.execute(f"SELECT count(*) FROM {gold}").fetchall()[0][0]
    assert s == g


def test_control_1_unique_people(wh):
    assert compute(wh[0], "unique_people", ADMIN)["value"] == 560


def test_control_2_offer_as_at_31_march(wh):
    r = compute(wh[0], "applications_at_stage_asof", ADMIN, stage="Offer", as_of="2026-03-31")
    assert r["value"] == 32


def test_control_3_median_time_to_hire(wh):
    r = compute(wh[0], "time_to_hire_median_days", ADMIN, start="2026-01-01", end="2026-06-30")
    assert r["value"] == 58


def test_control_4_engineering_salary(wh):
    assert compute(wh[0], "offered_salary_total", ADMIN, department="Engineering")["value"] == 200_700_000


def test_control_5_acceptance_rate(wh):
    r = compute(wh[0], "offer_acceptance_rate", ADMIN)
    # 164 / 320 = 51.25 exactly. Control states 51.2 (one dp, round-half-even). See RECONCILIATION.md.
    assert r["value"] == pytest.approx(51.25)
    assert Decimal("51.25").quantize(Decimal("0.1"), ROUND_HALF_EVEN) == Decimal("51.2")


def test_stage_history_is_contiguous(wh):
    con, *_ = wh
    gaps = con.execute("""
        SELECT count(*) FROM (
          SELECT valid_to, lead(valid_from) OVER (PARTITION BY application_key ORDER BY stage_seq) nxt
          FROM gold.fact_stage_history) WHERE nxt IS NOT NULL AND valid_to <> nxt""").fetchall()[0][0]
    one_current = con.execute("""
        SELECT count(*) FROM (SELECT application_key, count(*) FILTER (is_current) c
          FROM gold.fact_stage_history GROUP BY 1) WHERE c <> 1""").fetchall()[0][0]
    assert gaps == 0 and one_current == 0


def test_scoped_metric_is_subset(wh):
    con, *_ = wh
    keys = frozenset(r[0] for r in con.execute(
        "SELECT req_key FROM gold.dim_requisition WHERE hiring_manager_id = 'U005'").fetchall())
    hm = Scope("U005", "hiring_manager", keys)
    assert 0 < compute(con, "unique_people", hm)["value"] < 560
    assert compute(con, "unique_people", Scope("U999", "hiring_manager", frozenset()))["value"] == 0
