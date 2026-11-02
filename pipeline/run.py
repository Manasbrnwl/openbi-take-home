"""Entry point: python -m pipeline.run [--source DIR] [--warehouse FILE]"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import duckdb

from pipeline import bronze, gold, silver

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "northbeam_ats_pack"
DEFAULT_WAREHOUSE = Path(os.environ.get("NB_WAREHOUSE", ROOT / "warehouse" / "northbeam.duckdb"))


def run(source: Path = DEFAULT_SOURCE, warehouse: Path = DEFAULT_WAREHOUSE) -> dict:
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with duckdb.connect(str(warehouse)) as con:
        con.execute("BEGIN")
        try:
            landed = bronze.load(con, source)
            silver.build(con)
            gold.build(con)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        counts = {
            t: con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
            for t in [
                "bronze.candidates", "silver.candidates", "gold.dim_candidate",
                "gold.fact_application", "gold.fact_stage_history", "gold.fact_offer",
                "gold.fact_interview", "gold.dim_requisition", "gold.dim_user",
            ]
        }
    return {"landed": landed, "counts": counts, "seconds": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--warehouse", type=Path, default=DEFAULT_WAREHOUSE)
    a = ap.parse_args()
    out = run(a.source, a.warehouse)
    for k, v in out["landed"].items():
        print(f"bronze  {k:<14} {v}")
    for k, v in out["counts"].items():
        print(f"rows    {k:<26} {v}")
    print(f"done in {out['seconds']}s -> {a.warehouse}")
