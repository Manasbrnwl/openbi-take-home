"""Regression tests for the findings in docs/SECURITY_REVIEW.md. Each was written failing first.

Each test builds its own app (own login throttle) so lockouts can't leak into other test modules.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PASSWORD = "review-password"
HM = "uday.varma@northbeam.example"
ADMIN = "admin.one@northbeam.example"


def make_client(warehouse, env="prod"):
    settings = Settings(env=env, warehouse_path=warehouse, jwt_secret="s" * 48,
                        demo_password=PASSWORD, bcrypt_rounds=4)
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def client(fixture_warehouse):
    with make_client(fixture_warehouse) as c:
        yield c


def admin_headers(c):
    r = c.post("/auth/login", json={"email": ADMIN, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# SR-1: unlimited password guessing ------------------------------------------------------

def test_sr1_login_locks_after_repeated_failures(client):
    for _ in range(5):
        assert client.post("/auth/login", json={"email": HM, "password": "guess"}).status_code == 401
    locked = client.post("/auth/login", json={"email": HM, "password": "guess"})
    assert locked.status_code == 429 and "retry-after" in locked.headers
    # even the right password is refused while locked, so guessing can't continue
    assert client.post("/auth/login", json={"email": HM, "password": PASSWORD}).status_code == 429
    # other accounts are unaffected
    assert client.post("/auth/login", json={"email": ADMIN, "password": PASSWORD}).status_code == 200


def test_sr1_throttle_does_not_reveal_which_emails_exist(client):
    def statuses(email):
        return [client.post("/auth/login", json={"email": email, "password": "guess"}).status_code
                for _ in range(6)]
    assert statuses("nobody@northbeam.example") == statuses(HM) == [401] * 5 + [429]


def test_sr1_throttle_key_is_normalised(client):
    for i in range(5):
        client.post("/auth/login", json={"email": f"  {HM.upper() if i % 2 else HM} ", "password": "guess"})
    assert client.post("/auth/login", json={"email": HM, "password": "guess"}).status_code == 429


def test_sr1_success_resets_the_counter(client):
    for _ in range(4):
        client.post("/auth/login", json={"email": HM, "password": "guess"})
    assert client.post("/auth/login", json={"email": HM, "password": PASSWORD}).status_code == 200
    for _ in range(4):
        assert client.post("/auth/login", json={"email": HM, "password": "guess"}).status_code == 401


# SR-2: unauthenticated 500 from an over-long password ------------------------------------

@pytest.mark.parametrize("email", [HM, "nobody@northbeam.example"])
@pytest.mark.parametrize("length", [73, 10_000])
def test_sr2_overlong_password_is_401_not_500(client, email, length):
    r = client.post("/auth/login", json={"email": email, "password": "a" * length})
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid email or password"}


def test_sr2_overlong_password_never_matches_by_prefix(fixture_warehouse):
    # bcrypt < 5 silently truncated at 72 bytes; the correct password plus junk must still fail.
    settings = Settings(env="prod", warehouse_path=fixture_warehouse, jwt_secret="s" * 48,
                        demo_password="p" * 72, bcrypt_rounds=4)
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        assert c.post("/auth/login", json={"email": HM, "password": "p" * 72}).status_code == 200
        assert c.post("/auth/login", json={"email": HM, "password": "p" * 72 + "junk"}).status_code == 401


# SR-3: authenticated input that crashes the server --------------------------------------

@pytest.mark.parametrize("page", ["922337203685477580", "9223372036854775807", "10000000000000000000"])
def test_sr3_huge_page_is_rejected_not_500(client, page):
    assert client.get("/applications", headers=admin_headers(client), params={"page": page}).status_code == 422


@pytest.mark.parametrize("name,params", [
    ("_test_overflow", {"when": "9999-12-31"}),
])
def test_sr3_overflow_in_metric_is_400(client, name, params, monkeypatch):
    # Mirrors what the real date metrics do with as_of=9999-12-31 (date + 1 day overflows).
    import datetime

    import metrics.definitions as defs

    def fn(con, scope, when):
        datetime.date.fromisoformat(when) + datetime.timedelta(days=1)

    monkeypatch.setitem(defs.METRICS, name, {"label": "x", "unit": "count", "description": "x", "fn": fn})
    assert client.get(f"/metrics/{name}", headers=admin_headers(client), params=params).status_code == 400


def test_sr3_bad_param_errors_do_not_echo_internals(client, monkeypatch):
    import metrics.definitions as defs

    def fn(con, scope):
        return {}

    monkeypatch.setitem(defs.METRICS, "_test_noargs", {"label": "x", "unit": "count", "description": "x", "fn": fn})
    r = client.get("/metrics/_test_noargs", headers=admin_headers(client), params={"bogus": "1"})
    assert r.status_code == 400
    assert "fn()" not in r.text and "keyword argument" not in r.text


# SR-4: API schema published to anonymous users -------------------------------------------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_sr4_api_docs_hidden_outside_dev(client, path):
    assert client.get(path).status_code == 404


def test_sr4_api_docs_available_in_dev(fixture_warehouse):
    with make_client(fixture_warehouse, env="dev") as c:
        assert c.get("/openapi.json").status_code == 200
