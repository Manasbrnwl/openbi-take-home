"""Guard: metric arithmetic lives only in metrics/. Fails if a definition is copied elsewhere."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ["app", "frontend"]

# Fragments that only a metric definition would need.
FORBIDDEN = [
    r"\bmedian\s*\(", r"\bquantile", r"date_diff", r"status\s*=\s*'accepted'",
    r"'accepted'\s*,\s*'declined'", r"\bvalid_from\b", r"\bvalid_to\b",
    r"annual_salary", r"\*\s*100\b", r"/\s*100\b", r"toFixed\s*\(",
]


def test_no_metric_logic_outside_metric_layer():
    hits = []
    for d in GUARDED:
        for p in (ROOT / d).rglob("*"):
            if p.suffix not in {".py", ".js", ".ts", ".html", ".sql"} or "__pycache__" in p.parts:
                continue
            text = p.read_text("utf-8", errors="ignore")
            for pat in FORBIDDEN:
                for m in re.finditer(pat, text):
                    line = text[: m.start()].count("\n") + 1
                    hits.append(f"{p.relative_to(ROOT)}:{line} matches {pat!r}")
    assert not hits, "metric logic outside metrics/:\n" + "\n".join(hits)
