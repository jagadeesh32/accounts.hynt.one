def test_health(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_session_endpoint_is_safe_when_signed_out(client):
    assert client.get("/api/v1/auth/session").json() == {"authenticated": False}


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    a = client.post("/api/v1/auth/login", json={"email": "admin@hynt.one", "password": "nope-nope-nope"})
    b = client.post("/api/v1/auth/login", json={"email": "ghost@hynt.one", "password": "nope-nope-nope"})
    assert a.status_code == b.status_code == 401
    # Same body too: any difference is an account-existence oracle.
    assert a.json() == b.json()


def test_login_sets_an_httponly_cookie(superadmin):
    cookie = [c for c in superadmin.cookies.jar if c.name == "hynt_sso"][0]
    assert cookie.has_nonstandard_attr("HttpOnly")


def test_me_requires_a_session(client):
    assert client.get("/api/v1/me").status_code == 401


def test_me_returns_the_profile(superadmin):
    assert superadmin.get("/api/v1/me").json()["email"] == "admin@hynt.one"


def test_launcher_lists_every_platform(superadmin):
    platforms = superadmin.get("/api/v1/me/platforms").json()["platforms"]
    assert {p["slug"] for p in platforms} == {"terminal", "xterminal", "intelligence"}
    assert all(p["member"] for p in platforms)


def test_logout_ends_the_session(superadmin):
    assert superadmin.post("/api/v1/auth/logout").status_code == 200
    assert superadmin.get("/api/v1/me").status_code == 401


def test_sessions_list_marks_the_current_device(superadmin):
    sessions = superadmin.get("/api/v1/auth/sessions").json()["sessions"]
    assert len([s for s in sessions if s["current"]]) == 1
