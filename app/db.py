"""Read-only DuckDB access. One shared read-only connection; one cursor per request."""
from __future__ import annotations

import os
from collections.abc import Iterator

import duckdb
from fastapi import Request


def open_warehouse(path: str) -> duckdb.DuckDBPyConnection:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"warehouse not found at {path!r}; build it with `python -m pipeline.run` "
            "or point NB_WAREHOUSE at a DuckDB file"
        )
    return duckdb.connect(path, read_only=True)


def get_con(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    cur = request.app.state.con.cursor()
    try:
        yield cur
    finally:
        cur.close()


def rows_as_dicts(cur: duckdb.DuckDBPyConnection) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
