"""Access control: the scored part. Every test here goes through the HTTP layer with TestClient.

Ownership in the fixture (tests/conftest.py):
  U005 (HM) owns REQ-1003, REQ-1005     U006 (HM) owns REQ-1001, REQ-1004
  U001 (rec) has REQ-1001, REQ-1003     U002 (rec) has REQ-1004, REQ-1005
  U013 admin; orphans A00009, A00010 (req_key -1)
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import metrics.definitions as metric_defs
from app.config import Settings
from app.main import create_app

SECRET = "test-secret-" + "x" * 40
PASSWORD = "test-password"
EMAIL = {
    "U001": "naveen.malhotra@northbeam.example",
    "U002": "gaurav.khanna@northbeam.example",
    "U005": "uday.varma@northbeam.example",
    "U006": "harsh.agarwal@northbeam.example",
    "U013": "admin.one@northbeam.example",
    "U099": "odd.role@northbeam.example",
}
REQS_OF = {
    "U005": {"REQ-1003", "REQ-1005"},
    "U006": {"REQ-1001", "REQ-1004"},
    "U001": {"REQ-1001", "REQ-1003"},
    "U002": {"REQ-1004", "REQ-1005"},
}
ALL_REAL_REQS = {"REQ-1001", "REQ-1003", "REQ-1004", "REQ-1005"}
ORPHAN_APPS = {"A00009", "A00010"}


def _app_count(con, scope, **params):
    """Test-only metric: scoped application count, shaped like a real metric result."""
    where, p = scope.sql_filter("req_key")
    (n,) = con.execute(f"SELECT count(*) FROM gold.fact_application WHERE {where}", p).fetchone()
    return {"metric": "_test_app_count", "label": "Apps", "unit": "count", "value": n,
            "breakdown": None, "params": params}


@pytest.fixture(scope="module")
def client(fixture_warehouse):
    settings = Settings(env="test", warehouse_path=fixture_warehouse, jwt_secret=SECRET,
                        demo_password=PASSWORD, bcrypt_rounds=4)
    mp = pytest.MonkeyPatch()
    mp.setitem(metric_defs.METRICS, "_test_app_count",
               {"label": "Apps", "unit": "count", "description": "test", "fn": _app_count})
    with TestClient(create_app(settings)) as c:
        yield c
    mp.undo()


def login(client, user_id) -> dict:
    r = client.post("/auth/login", json={"email": EMAIL[user_id], "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def req_ids(client, headers, params=None) -> set[str]:
    r = client.get("/requisitions", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return {x["req_id"] for x in r.json()}


def app_ids(client, headers, params=None) -> set[str]:
    r = client.get("/applications", headers=headers, params={"page_size": 100, **(params or {})})
    assert r.status_code == 200, r.text
    return {x["application_id"] for x in r.json()["items"]}


# ---------- authentication ----------

def test_login_rejects_wrong_password_and_unknown_email(client):
    wrong = client.post("/auth/login", json={"email": EMAIL["U005"], "password": "nope"})
    unknown = client.post("/auth/login", json={"email": "nobody@northbeam.example", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # same message: no email enumeration


def test_token_carries_only_sub_and_exp(client):
    token = login(client, "U005")["Authorization"].split()[1]
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "exp"} and claims["sub"] == "U005"


@pytest.mark.parametrize("path", ["/me", "/metrics", "/metrics/_test_app_count", "/requisitions",
                                  "/requisitions/REQ-1003/applications", "/applications"])
def test_every_data_endpoint_requires_auth(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Basic dTpw"}).status_code == 401


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _exp(minutes=30):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def forged_tokens() -> dict[str, str]:
    good_admin = jwt.encode({"sub": "U013", "exp": _exp()}, SECRET, algorithm="HS256")
    good_hm = jwt.encode({"sub": "U005", "exp": _exp()}, SECRET, algorithm="HS256")
    h, _, sig = good_hm.split(".")
    admin_payload = _b64({"sub": "U013", "exp": int(_exp().timestamp())})
    none_header = _b64({"alg": "none", "typ": "JWT"})
    return {
        "wrong_secret": jwt.encode({"sub": "U013", "exp": _exp()}, "attacker-secret-" + "y" * 40, algorithm="HS256"),
        "alg_none": f"{none_header}.{admin_payload}.",
        "alg_none_with_sig": f"{none_header}.{good_admin.split('.')[1]}.{good_admin.split('.')[2]}",
        "other_alg_hs512": jwt.encode({"sub": "U013", "exp": _exp()}, SECRET, algorithm="HS512"),
        "expired": jwt.encode({"sub": "U013", "exp": _exp(-1)}, SECRET, algorithm="HS256"),
        "no_exp": jwt.encode({"sub": "U013"}, SECRET, algorithm="HS256"),
        "no_sub": jwt.encode({"exp": _exp()}, SECRET, algorithm="HS256"),
        "non_string_sub": jwt.encode({"sub": 13, "exp": _exp()}, SECRET, algorithm="HS256"),
        # HM's genuine header+signature with the payload swapped to claim admin
        "payload_swapped": f"{h}.{admin_payload}.{sig}",
        "unknown_user": jwt.encode({"sub": "U404", "exp": _exp()}, SECRET, algorithm="HS256"),
        "garbage": "not-a-jwt",
    }


@pytest.mark.parametrize("kind", list(forged_tokens()))
def test_tampered_tokens_are_rejected(client, kind):
    token = forged_tokens()[kind]
    for path in ("/me", "/requisitions", "/applications", "/metrics/_test_app_count",
                 "/requisitions/REQ-1003/applications"):
        r = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, (kind, path, r.status_code)


def test_role_claim_in_token_is_ignored(client):
    # A validly signed token that *also claims* admin still only gets its sub's real scope.
    token = jwt.encode({"sub": "U005", "role": "admin", "req_keys": None, "exp": _exp()}, SECRET, algorithm="HS256")
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/me", headers=h).json()["role"] == "hiring_manager"
    assert req_ids(client, h) == REQS_OF["U005"]


def test_unscopable_role_is_denied(client):
    h = login(client, "U099")  # role 'auditor' has no scope rule: denied, not given everything
    assert client.get("/requisitions", headers=h).status_code == 401


# ---------- scope ----------

def test_hm_cannot_open_another_hms_requisition(client):
    h = login(client, "U005")
    other = client.get("/requisitions/REQ-1001/applications", headers=h)  # owned by U006
    assert other.status_code == 404
    # indistinguishable from a req that doesn't exist
    missing = client.get("/requisitions/REQ-0000/applications", headers=h)
    assert missing.status_code == 404 and missing.json() == other.json()
    own = client.get("/requisitions/REQ-1003/applications", headers=h)
    assert own.status_code == 200
    assert {a["application_id"] for a in own.json()} == {"A00003", "A00004", "A00005"}


@pytest.mark.parametrize("user,expected", list(REQS_OF.items()))
def test_users_see_exactly_their_requisitions(client, user, expected):
    assert req_ids(client, login(client, user)) == expected


def test_recruiter_sees_exactly_reqs_where_they_are_recruiter(client):
    h = login(client, "U001")
    assert req_ids(client, h) == {"REQ-1001", "REQ-1003"}
    assert app_ids(client, h) == {"A00001", "A00002", "A00003", "A00004", "A00005"}
    assert client.get("/requisitions/REQ-1004/applications", headers=h).status_code == 404
    assert client.get("/me", headers=h).json()["visible_requisitions"] == 2


TAMPER_VARIANTS = [
    {"params": {"user_id": "U013"}},
    {"params": {"role": "admin"}},
    {"params": {"req_keys": "1,3,4,5"}},
    {"params": {"scope": "admin"}},
    {"headers": {"X-User-Id": "U013"}},
    {"headers": {"X-Role": "admin"}},
    {"headers": {"X-Forwarded-User": "U013"}},
]


@pytest.mark.parametrize("variant", TAMPER_VARIANTS, ids=lambda v: json.dumps(v))
def test_identity_params_and_headers_change_nothing(client, variant):
    h = login(client, "U005")
    paths = ["/requisitions", "/applications", "/me", "/metrics/_test_app_count"]
    base = {p: client.get(p, headers=h).json() for p in paths}
    hh = {**h, **variant.get("headers", {})}
    q = variant.get("params", {})
    for p in paths:
        got = client.get(p, headers=hh, params=q).json()
        if p.startswith("/metrics/"):
            assert got["value"] == base[p]["value"], (p, variant)
        else:
            assert got == base[p], (p, variant)
    assert client.get("/requisitions/REQ-1001/applications", headers=hh, params=q).status_code == 404


def test_metric_values_are_scoped(client):
    def value(user):
        return client.get("/metrics/_test_app_count", headers=login(client, user)).json()["value"]

    admin, hm5, hm6 = value("U013"), value("U005"), value("U006")
    assert admin == 10  # 8 real + 2 orphans
    assert hm5 == 5     # REQ-1003 (3) + REQ-1005 (2)
    assert hm6 == 3     # REQ-1001 (2) + REQ-1004 (1)


def test_metric_route_passes_server_built_scope_for_every_metric(client, monkeypatch):
    """Whatever metrics session A defines, the route hands compute() the token's scope, and
    identity-looking query params never reach the metric function."""
    seen = []

    def spy(con, name, scope, **params):
        seen.append((name, scope, params))
        return {"metric": name, "value": None}

    monkeypatch.setattr("metrics.compute", spy)
    h = login(client, "U005")
    names = [m["name"] for m in client.get("/metrics", headers=h).json()]
    assert names
    for name in names:
        client.get(f"/metrics/{name}", headers=h,
                   params={"user_id": "U013", "role": "admin", "scope": "x", "req_keys": "1", "asof": "2026-01-01"})
    assert [s[0] for s in seen] == names
    for _, scope, params in seen:
        assert (scope.user_id, scope.role, scope.req_keys) == ("U005", "hiring_manager", frozenset({3, 5}))
        assert params == {"asof": "2026-01-01"}


def test_orphan_applications_visible_to_admin_only(client):
    admin = app_ids(client, login(client, "U013"))
    assert ORPHAN_APPS <= admin and len(admin) == 10
    for user in ("U001", "U002", "U005", "U006"):
        assert not (ORPHAN_APPS & app_ids(client, login(client, user))), user
    # the Unknown requisition member is reachable by admin only
    assert client.get("/requisitions/UNKNOWN/applications", headers=login(client, "U005")).status_code == 404
    unk = client.get("/requisitions/UNKNOWN/applications", headers=login(client, "U013"))
    assert {a["application_id"] for a in unk.json()} == ORPHAN_APPS


def test_admin_sees_all_requisitions(client):
    assert ALL_REAL_REQS <= req_ids(client, login(client, "U013"))


def test_pii_only_on_entitled_rows(client):
    h5, h6 = login(client, "U005"), login(client, "U006")
    u5_apps = client.get("/applications", headers=h5, params={"page_size": 100}).json()["items"]
    u6_apps = client.get("/applications", headers=h6, params={"page_size": 100}).json()["items"]
    u5_cands = {a["candidate_email"] for a in u5_apps}
    u5_body = json.dumps(u5_apps)
    # Every U006-only candidate's email/phone is absent from U005's responses.
    for a in u6_apps:
        if a["candidate_email"] not in u5_cands:
            assert a["candidate_email"] not in u5_body and a["candidate_phone"] not in u5_body


def test_page_size_is_capped(client):
    h = login(client, "U013")
    assert client.get("/applications", headers=h, params={"page_size": 101}).status_code == 422
    r = client.get("/applications", headers=h, params={"page_size": 3, "page": 2}).json()
    assert r["total"] == 10 and len(r["items"]) == 3
