"""Single source of metric definitions. (Being written by session A — stub for now.)"""
from __future__ import annotations

from metrics.scope import Scope

METRICS: dict = {}


def list_metrics() -> list[dict]:
    return [{"name": k, **{x: v[x] for x in ("label", "unit", "description")}} for k, v in METRICS.items()]


def compute(con, name: str, scope: Scope, **params) -> dict:
    if name not in METRICS:
        raise KeyError(name)
    return METRICS[name]["fn"](con, scope, **params)
