"""Access control against the real warehouse (skipped until `python -m pipeline.run` has built it).

The fixture tests prove the mechanism; these prove it on the real data and real metrics:
scope sets match dim_requisition exactly, recruiter scopes partition the non-orphan data, and
every metric is computed under the caller's scope.
"""
from __future__ import annotations

import os

import duckdb
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

WAREHOUSE = os.environ.get("NB_WAREHOUSE", "warehouse/northbeam.duckdb")
PASSWORD = "real-wh-test-password"
pytestmark = pytest.mark.skipif(not os.path.exists(WAREHOUSE), reason="real warehouse not built")


@pytest.fixture(scope="module")
def ctx():
    settings = Settings(env="test", warehouse_path=WAREHOUSE, jwt_secret="r" * 48,
                        demo_password=PASSWORD, bcrypt_rounds=4)
    with TestClient(create_app(settings)) as c:
        con = c.app.state.con.cursor()
        users = con.execute("SELECT user_id, email, role FROM gold.dim_user ORDER BY user_id").fetchall()
        reqs = con.execute(
            "SELECT req_id, hiring_manager_id, recruiter_id FROM gold.dim_requisition WHERE req_key >= 0"
        ).fetchall()
        headers = {}
        for uid, email, _ in users:
            r = c.post("/auth/login", json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, (uid, r.text)
            headers[uid] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        yield {"c": c, "users": users, "reqs": reqs, "h": headers}
        con.close()


def _req_ids(c, h):
    return {r["req_id"] for r in c.get("/requisitions", headers=h).json()}


def _total(c, h):
    return c.get("/applications", headers=h, params={"page_size": 1}).json()["total"]


def test_each_user_sees_exactly_their_reqs(ctx):
    c, h = ctx["c"], ctx["h"]
    for uid, _, role in ctx["users"]:
        got = _req_ids(c, h[uid])
        if role == "admin":
            assert {r[0] for r in ctx["reqs"]} <= got and "UNKNOWN" in got
        else:
            col = 1 if role == "hiring_manager" else 2
            assert got == {r[0] for r in ctx["reqs"] if r[col] == uid}, uid


def test_u005_cannot_open_other_hms_reqs(ctx):
    c, h = ctx["c"], ctx["h"]["U005"]
    others = [r[0] for r in ctx["reqs"] if r[1] != "U005"]
    assert others
    for req_id in others:
        assert c.get(f"/requisitions/{req_id}/applications", headers=h).status_code == 404, req_id


def test_recruiter_scopes_partition_non_orphan_applications(ctx):
    c, h = ctx["c"], ctx["h"]
    admin = next(u for u, _, r in ctx["users"] if r == "admin")
    orphans = c.get("/requisitions/UNKNOWN/applications", headers=h[admin]).json()
    assert orphans and all(a["is_orphan"] for a in orphans)
    recruiter_sum = sum(_total(c, h[u]) for u, _, r in ctx["users"] if r == "recruiter")
    hm_sum = sum(_total(c, h[u]) for u, _, r in ctx["users"] if r == "hiring_manager")
    assert recruiter_sum + len(orphans) == _total(c, h[admin])
    assert hm_sum + len(orphans) == _total(c, h[admin])


def test_orphans_never_reach_non_admins(ctx):
    c, h = ctx["c"], ctx["h"]
    for uid, _, role in ctx["users"]:
        if role == "admin":
            continue
        items = c.get("/applications", headers=h[uid], params={"page_size": 100}).json()["items"]
        assert not any(a["is_orphan"] for a in items), uid
        assert c.get("/requisitions/UNKNOWN/applications", headers=h[uid]).status_code == 404


def test_hm_metrics_differ_from_admin_and_ignore_identity_params(ctx):
    c, h = ctx["c"], ctx["h"]
    names = [m["name"] for m in c.get("/metrics", headers=h["U013"]).json()]
    for name in names:
        admin = c.get(f"/metrics/{name}", headers=h["U013"]).json()
        hm = c.get(f"/metrics/{name}", headers=h["U005"]).json()
        assert hm["value"] != admin["value"] or hm["breakdown"] != admin["breakdown"], name
        tampered = c.get(f"/metrics/{name}", headers={**h["U005"], "X-User-Id": "U013"},
                         params={"user_id": "U013", "role": "admin"}).json()
        assert tampered == hm, name


def test_bad_metric_params_are_400_not_500(ctx):
    c, h = ctx["c"], ctx["h"]["U013"]
    assert c.get("/metrics/unique_people", headers=h, params={"bogus": "1"}).status_code == 400
    assert c.get("/metrics/applications_received_mom", headers=h, params={"month": "garbage"}).status_code == 400
