def test_revocation_list_is_public_and_polled(client):
    body = client.get("/api/v1/revocations").json()
    assert "users" in body and "sessions" in body
    assert body["poll_after"] == 30


def test_superadmin_surface_needs_a_superadmin(client):
    assert client.get("/api/v1/superadmin/stats").status_code == 401


def test_stats(superadmin):
    stats = superadmin.get("/api/v1/superadmin/stats").json()
    assert stats["platforms"] == 3
    assert stats["clients"] == 3


def test_invite_creates_and_grants(superadmin):
    response = superadmin.post("/api/v1/admin/terminal/invite", json={
        "email": "newbie@example.com", "platform": "terminal", "role": "user",
    })
    assert response.status_code == 200
    assert response.json()["created"] is True

    members = superadmin.get("/api/v1/admin/terminal/members").json()["members"]
    assert any(m["email"] == "newbie@example.com" and m["role"] == "user" for m in members)


def test_suspending_publishes_a_revocation(superadmin):
    superadmin.post("/api/v1/admin/terminal/invite", json={
        "email": "leaver@example.com", "platform": "terminal", "role": "user",
    })
    users = superadmin.get("/api/v1/superadmin/users?q=leaver").json()["users"]
    user_id = users[0]["id"]

    assert superadmin.post(f"/api/v1/superadmin/users/{user_id}/suspend").status_code == 200
    assert user_id in superadmin.get("/api/v1/revocations").json()["users"]


def test_a_suspended_account_cannot_sign_in(superadmin, client):
    response = superadmin.post("/api/v1/admin/terminal/invite", json={
        "email": "blocked@example.com", "platform": "terminal", "role": "user",
    })
    password = response.json()["temp_password"]
    user_id = superadmin.get("/api/v1/superadmin/users?q=blocked").json()["users"][0]["id"]
    superadmin.post(f"/api/v1/superadmin/users/{user_id}/suspend")

    assert client.post("/api/v1/auth/login", json={
        "email": "blocked@example.com", "password": password,
    }).status_code == 403


def test_rotating_a_key_keeps_the_old_public_key_published(superadmin):
    before = {k["kid"] for k in superadmin.get("/.well-known/jwks.json").json()["keys"]}
    superadmin.post("/api/v1/superadmin/keys/rotate")
    after = {k["kid"] for k in superadmin.get("/.well-known/jwks.json").json()["keys"]}
    # Rotation adds; it must never drop a key whose tokens are still alive.
    assert before.issubset(after)
    assert len(after) > len(before)


def test_a_non_member_cannot_reach_another_platforms_console(superadmin):
    response = superadmin.post("/api/v1/admin/terminal/invite", json={
        "email": "outsider@example.com", "platform": "terminal", "role": "user",
    })
    password = response.json()["temp_password"]

    import httpx
    with httpx.Client(base_url=str(superadmin.base_url), timeout=10) as c:
        c.post("/api/v1/auth/login", json={"email": "outsider@example.com", "password": password})
        assert c.get("/api/v1/admin/xterminal/members").status_code == 403
        assert c.get("/api/v1/superadmin/stats").status_code == 403
