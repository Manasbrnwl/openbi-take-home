from __future__ import annotations

import pytest

from app.config import ConfigError, Settings
from tests.test_access_control import client, login  # noqa: F401  (reuse the module fixture)


def test_refuses_to_start_without_secret_outside_dev(monkeypatch):
    for k in ("NB_ENV", "NB_JWT_SECRET", "NB_DEMO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()  # no NB_ENV means prod
    monkeypatch.setenv("NB_ENV", "prod")
    monkeypatch.setenv("NB_JWT_SECRET", "short")
    monkeypatch.setenv("NB_DEMO_PASSWORD", "x")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_dev_defaults_use_random_secret(monkeypatch):
    monkeypatch.setenv("NB_ENV", "dev")
    monkeypatch.delenv("NB_JWT_SECRET", raising=False)
    monkeypatch.delenv("NB_DEMO_PASSWORD", raising=False)
    a, b = Settings.from_env(), Settings.from_env()
    assert a.jwt_secret != b.jwt_secret and a.demo_password == "northbeam-demo"


def test_me(client):  # noqa: F811
    r = client.get("/me", headers=login(client, "U005")).json()
    assert r["user_id"] == "U005" and r["role"] == "hiring_manager" and r["visible_requisitions"] == 2


def test_unknown_metric_404(client):  # noqa: F811
    assert client.get("/metrics/no_such_metric", headers=login(client, "U013")).status_code == 404


def test_metric_result_returned_unchanged(client):  # noqa: F811
    r = client.get("/metrics/_test_app_count", headers=login(client, "U013"), params={"x": "1"}).json()
    assert r == {"metric": "_test_app_count", "label": "Apps", "unit": "count", "value": 10,
                 "breakdown": None, "params": {"x": "1"}}


def test_stage_filter(client):  # noqa: F811
    r = client.get("/applications", headers=login(client, "U013"), params={"stage": "Applied"}).json()
    assert r["total"] == 4 and {a["current_stage"] for a in r["items"]} == {"Applied"}


def test_healthz_is_public_and_returns_no_data(client):  # noqa: F811
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_frontend_served_with_csp(client):  # noqa: F811
    r = client.get("/")
    assert r.status_code == 200 and "app.js" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
