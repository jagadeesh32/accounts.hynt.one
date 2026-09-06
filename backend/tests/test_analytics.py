"""The analytics surfaces.

These assert the shape the board actually consumes — dense daily series, a
previous-window comparison, and the guards. A chart drawn from a sparse series
runs a smooth line straight across a five-day outage, so "every day present" is
a contract, not a detail.
"""


def test_analytics_needs_a_superadmin(client):
    assert client.get("/api/v1/superadmin/analytics").status_code == 401


def test_estate_analytics_returns_dense_series(superadmin):
    body = superadmin.get("/api/v1/superadmin/analytics?days=30").json()

    assert body["window_days"] == 30
    for name, points in body["series"].items():
        assert len(points) == 30, f"{name} is not dense"
        assert points == sorted(points, key=lambda p: p["d"]), f"{name} is out of order"
        assert all(isinstance(p["v"], int) for p in points)

    # Signing in to run this test is itself an audited login, so the window has
    # at least one of them and the totals have to agree with the series.
    assert sum(p["v"] for p in body["series"]["logins"]) >= 1
    assert body["totals"]["users"] >= 1
    assert body["totals"]["superadmins"] >= 1
    assert body["totals"]["superadmins_without_mfa"] <= body["totals"]["superadmins"]

    assert {"signups", "logins", "failures", "active_users", "admin_actions"} <= set(body["previous"])
    assert body["recency"]["total"] == body["totals"]["users"]
    assert all(0 <= c["dow"] <= 6 and 0 <= c["hour"] <= 23 for c in body["heatmap"])


def test_the_window_is_bounded(superadmin):
    assert superadmin.get("/api/v1/superadmin/analytics?days=3").status_code == 422
    assert superadmin.get("/api/v1/superadmin/analytics?days=4000").status_code == 422
    assert len(superadmin.get("/api/v1/superadmin/analytics?days=7").json()["series"]["logins"]) == 7


def test_failed_sign_ins_are_counted_and_attributed(superadmin, client):
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"email": "admin@hynt.one", "password": "wrong-on-purpose"})

    body = superadmin.get("/api/v1/superadmin/analytics?days=7").json()
    assert sum(p["v"] for p in body["series"]["failures"]) >= 3
    assert sum(s["count"] for s in body["failure_sources"]) >= 3


def test_platform_analytics_is_scoped_to_the_platform(superadmin):
    superadmin.post("/api/v1/admin/terminal/invite", json={
        "email": "analytics-member@example.com", "platform": "terminal", "role": "user",
    })

    body = superadmin.get("/api/v1/admin/terminal/analytics?days=30").json()
    assert body["platform"]["slug"] == "terminal"
    assert body["totals"]["members"] >= 1
    assert len(body["series"]["joined"]) == 30
    assert sum(p["v"] for p in body["series"]["joined"]) >= 1
    # Roles and plans are per-platform rollups, and every member lands in exactly
    # one of each — otherwise the stacked bars above them do not add up.
    assert sum(r["count"] for r in body["roles"]) == body["totals"]["members"]
    assert sum(p["count"] for p in body["plans"]) == body["totals"]["members"]
    assert body["recency"]["total"] == body["totals"]["members"]

    assert superadmin.get("/api/v1/admin/no-such-platform/analytics").status_code == 404
