"""Bronze: land every source file as-is (all values as text) with lineage.

Idempotency: each file is fingerprinted (SHA-256). A file whose hash is already in
`bronze._load_log` is skipped, so re-running never duplicates rows. A changed file lands as a
new batch; Silver reads only the latest batch per source.
"""
from __future__ import annotations

import csv
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

SOURCES = {
    "candidates": "candidates.csv",
    "applications": "applications.csv",
    "stage_events": "stage_events.csv",
    "requisitions": "requisitions.json",
    "users": "users.json",
    "interviews": "interviews.json",
    "offers": "offers.xlsx",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _read_rows(path: Path) -> list[dict[str, str | None]]:
    """Return rows as dicts of raw text. No cleaning here — that is Silver's job."""
    if path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]
    if path.suffix == ".json":
        return [{k: _as_text(v) for k, v in r.items()} for r in json.loads(path.read_text("utf-8"))]
    if path.suffix == ".xlsx":
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [str(h) for h in next(rows)]
        out = [dict(zip(header, map(_as_text, r))) for r in rows if any(c is not None for c in r)]
        wb.close()
        return out
    raise ValueError(f"unsupported source type: {path}")


def load(con, source_dir: Path) -> dict[str, str]:
    """Land all sources. Returns {source: 'loaded' | 'skipped (unchanged)'}."""
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    con.execute(
        """CREATE TABLE IF NOT EXISTS bronze._load_log (
            batch_id VARCHAR, source VARCHAR, source_file VARCHAR, file_sha256 VARCHAR,
            row_count INTEGER, loaded_at TIMESTAMPTZ)"""
    )
    status = {}
    for source, filename in SOURCES.items():
        path = source_dir / filename
        digest = _sha256(path)
        seen = con.execute(
            "SELECT 1 FROM bronze._load_log WHERE source = ? AND file_sha256 = ?", [source, digest]
        ).fetchall()
        if seen:
            status[source] = "skipped (unchanged)"
            continue

        rows = _read_rows(path)
        cols = list(rows[0].keys())
        batch_id = str(uuid.uuid4())
        loaded_at = datetime.now(timezone.utc)
        col_defs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        con.execute(
            f"""CREATE TABLE IF NOT EXISTS bronze.{source} ({col_defs},
                _source_file VARCHAR, _source_row INTEGER, _file_sha256 VARCHAR,
                _batch_id VARCHAR, _loaded_at TIMESTAMPTZ)"""
        )
        placeholders = ", ".join("?" * (len(cols) + 5))
        con.executemany(
            f"INSERT INTO bronze.{source} ({', '.join(chr(34) + c + chr(34) for c in cols)}, "
            f"_source_file, _source_row, _file_sha256, _batch_id, _loaded_at) VALUES ({placeholders})",
            [[r.get(c) for c in cols] + [filename, i + 1, digest, batch_id, loaded_at] for i, r in enumerate(rows)],
        )
        con.execute(
            "INSERT INTO bronze._load_log VALUES (?, ?, ?, ?, ?, ?)",
            [batch_id, source, filename, digest, len(rows), loaded_at],
        )
        status[source] = f"loaded {len(rows)} rows"
    return status
