"""Superadmin control: access, devices, activity, revocation and deletion."""

from __future__ import annotations

import pytest

from tests.conftest import SUPERADMIN_EMAIL
from tests.helpers import authorize, get_token, redirect_params


@pytest.fixture
def victim(admin):
    """A disposable account, cleaned up afterwards so tests do not interfere."""
    email = "victim@hynt.one"
    for row in admin.get(f"/api/v1/admin/users?q={email}").json()["users"]:
        admin.request("DELETE", f"/api/v1/admin/users/{row['id']}",
                      json={"confirm_email": row["email"]})

    response = admin.post(
        "/api/v1/admin/users",
        json={"email": email, "password": "VictimPass!2026", "full_name": "Victim"},
    )
    assert response.status_code == 201, response.text
    user = response.json()["user"]
    yield user

    admin.request("DELETE", f"/api/v1/admin/users/{user['id']}",
                  json={"confirm_email": user["email"]})


@pytest.fixture
def victim_client(server, victim):
    import httpx

    with httpx.Client(base_url=server, follow_redirects=False, timeout=10) as client:
        client.post("/api/v1/auth/login",
                    json={"email": victim["email"], "password": "VictimPass!2026"})
        yield client


# --------------------------------------------------------------------------- #
#  Visibility
# --------------------------------------------------------------------------- #
def test_new_accounts_get_default_access_everywhere(admin, victim):
    body = admin.get(f"/api/v1/admin/users/{victim['id']}/overview").json()
    access = {a["membership"]["platform"]["slug"]: a for a in body["access"]}
    assert set(access) == {"terminal", "xterminal", "intelligence"}
    assert all(a["membership"]["role"]["code"] == "user" for a in access.values())
    assert all(a["subscription"]["plan"]["code"] == "free" for a in access.values())


def test_overview_shows_devices_and_activity(admin, victim, victim_client):
    body = admin.get(f"/api/v1/admin/users/{victim['id']}/overview").json()
    assert len(body["sessions"]) >= 1
    assert any(entry["action"] == "auth.login.success" for entry in body["recent_activity"])


def test_login_history_records_ip_and_device(admin, victim, server):
    """IP comes from X-Forwarded-For, which is what the reverse proxy sets."""
    import httpx

    with httpx.Client(base_url=server, timeout=10) as client:
        client.post(
            "/api/v1/auth/login",
            json={"email": victim["email"], "password": "VictimPass!2026"},
            headers={"X-Forwarded-For": "203.0.113.42, 10.0.0.1",
                     "User-Agent": "Mozilla/5.0 (Macintosh) Chrome/131"},
        )

    logins = admin.get(f"/api/v1/admin/users/{victim['id']}/logins").json()["logins"]
    recorded = next(entry for entry in logins if entry["ip_address"])
    # The first hop is the client; the proxy's own address is discarded.
    assert recorded["ip_address"] == "203.0.113.42"
    assert "Chrome" in recorded["user_agent"]
    assert recorded["outcome"] == "success"


def test_failed_sign_ins_are_recorded(admin, victim, anon):
    anon.post("/api/v1/auth/login", json={"email": victim["email"], "password": "wrong"})
    logins = admin.get(f"/api/v1/admin/users/{victim['id']}/logins").json()["logins"]
    assert any(entry["outcome"] == "failed" for entry in logins)


def test_activity_covers_actions_done_to_the_account(admin, victim):
    """Both directions: what they did, and what was done to them. Showing only
    the first would hide exactly what an investigation needs."""
    admin.patch(f"/api/v1/admin/users/{victim['id']}", json={"full_name": "Renamed"})
    entries = admin.get(f"/api/v1/admin/users/{victim['id']}/activity").json()["entries"]
    assert any(entry["action"] == "admin.user.updated" for entry in entries)


# --------------------------------------------------------------------------- #
#  Access control
# --------------------------------------------------------------------------- #
def test_revoking_one_platform_leaves_the_others_alone(admin, victim, victim_client):
    terminal_token = get_token(victim_client, "terminal-web")
    get_token(victim_client, "xterminal-web")

    assert admin.post(
        f"/api/v1/admin/users/{victim['id']}/platforms/xterminal/revoke"
    ).status_code == 200

    # The revoked platform is refused at the door...
    _, response = authorize(victim_client, "xterminal-web")
    assert redirect_params(response)["error"] == "access_denied"

    # ...while the others keep working.
    _, response = authorize(victim_client, "terminal-web")
    assert "code" in redirect_params(response)
    assert terminal_token  # minted before the revocation, still for a live platform


def test_revocation_is_published_for_the_platforms_to_poll(admin, victim, victim_client):
    """Access tokens are verified locally, so revocation has to be published or
    it would not take effect until the token expired."""
    get_token(victim_client, "terminal-web")
    admin.post(f"/api/v1/admin/users/{victim['id']}/revoke", json={"reason": "test"})

    entries = admin.get("/api/v1/revocations").json()["revocations"]
    mine = [entry for entry in entries if entry["sub"] == victim["id"]]
    assert mine, "the revocation was not published"
    assert mine[0]["platform"] is None  # all platforms
    assert mine[0]["min_tv"] >= 2


def test_platform_scoped_revocation_names_the_platform(admin, victim):
    admin.post(f"/api/v1/admin/users/{victim['id']}/platforms/xterminal/revoke")
    entries = admin.get("/api/v1/revocations").json()["revocations"]
    mine = [e for e in entries if e["sub"] == victim["id"] and e["platform"] == "xterminal"]
    assert mine


def test_granting_access_back_restores_it(admin, victim, victim_client):
    admin.post(f"/api/v1/admin/users/{victim['id']}/platforms/xterminal/revoke")
    admin.post(f"/api/v1/admin/users/{victim['id']}/platforms/xterminal/grant",
               json={"role": "staff"})

    _, response = authorize(victim_client, "xterminal-web")
    assert "code" in redirect_params(response)


def test_revocation_list_exposes_nothing_identifying(anon):
    """It has to be readable without a credential — a platform whose credential
    expired must not silently stop enforcing revocations. So it carries opaque
    ids and nothing else."""
    body = anon.get("/api/v1/revocations").json()
    for entry in body["revocations"]:
        assert set(entry) <= {"sub", "platform", "min_tv", "at"}


# --------------------------------------------------------------------------- #
#  Devices
# --------------------------------------------------------------------------- #
def test_a_single_device_can_be_signed_out(admin, victim, victim_client, server):
    import httpx

    with httpx.Client(base_url=server, follow_redirects=False, timeout=10) as second:
        second.post("/api/v1/auth/login",
                    json={"email": victim["email"], "password": "VictimPass!2026"})

        sessions = admin.get(f"/api/v1/admin/users/{victim['id']}/sessions").json()["sessions"]
        assert len(sessions) >= 2

        admin.delete(f"/api/v1/admin/users/{victim['id']}/sessions/{sessions[0]['id']}")

        remaining = admin.get(f"/api/v1/admin/users/{victim['id']}/sessions").json()["sessions"]
        assert len(remaining) == len(sessions) - 1


def test_revoking_everything_ends_every_device(admin, victim, victim_client):
    admin.post(f"/api/v1/admin/users/{victim['id']}/revoke", json={"reason": "test"})
    assert admin.get(f"/api/v1/admin/users/{victim['id']}/sessions").json()["sessions"] == []


def test_suspension_blocks_sign_in(admin, victim, anon):
    admin.patch(f"/api/v1/admin/users/{victim['id']}", json={"status": "suspended"})
    response = anon.post("/api/v1/auth/login",
                         json={"email": victim["email"], "password": "VictimPass!2026"})
    assert response.status_code == 403
    assert response.json()["error"] == "account_suspended"


# --------------------------------------------------------------------------- #
#  Deletion
# --------------------------------------------------------------------------- #
def test_deletion_requires_the_email_as_confirmation(admin, victim):
    """Not ceremony: it is what stops a mis-aimed click on a list row deleting
    the wrong person."""
    response = admin.request("DELETE", f"/api/v1/admin/users/{victim['id']}",
                             json={"confirm_email": "someone-else@hynt.one"})
    assert response.status_code == 400
    assert response.json()["error"] == "confirmation_required"
    assert admin.get(f"/api/v1/admin/users/{victim['id']}/overview").status_code == 200


def test_deletion_removes_the_account(admin, victim):
    response = admin.request("DELETE", f"/api/v1/admin/users/{victim['id']}",
                             json={"confirm_email": victim["email"]})
    assert response.status_code == 200
    assert admin.get(f"/api/v1/admin/users/{victim['id']}/overview").status_code == 404


def test_the_audit_trail_outlives_the_account(admin, victim):
    """actor_user_id is ON DELETE SET NULL, so the record of what happened
    survives the account it happened to."""
    before = admin.get("/api/v1/admin/audit?limit=1").json()["total"]
    admin.request("DELETE", f"/api/v1/admin/users/{victim['id']}",
                  json={"confirm_email": victim["email"]})
    after = admin.get("/api/v1/admin/audit?limit=1").json()["total"]
    assert after > before


# --------------------------------------------------------------------------- #
#  Self-protection
# --------------------------------------------------------------------------- #
def test_a_superadmin_cannot_delete_themselves(admin):
    me = admin.get("/api/v1/auth/session").json()["user"]
    response = admin.request("DELETE", f"/api/v1/admin/users/{me['id']}",
                             json={"confirm_email": me["email"]})
    assert response.status_code == 403


def test_a_superadmin_cannot_revoke_their_own_access(admin):
    me = admin.get("/api/v1/auth/session").json()["user"]
    assert admin.post(f"/api/v1/admin/users/{me['id']}/revoke").status_code == 403


def test_a_superadmin_cannot_suspend_themselves(admin):
    me = admin.get("/api/v1/auth/session").json()["user"]
    response = admin.patch(f"/api/v1/admin/users/{me['id']}", json={"status": "suspended"})
    assert response.status_code == 403


def test_admin_routes_reject_a_non_superadmin(victim_client):
    assert victim_client.get("/api/v1/admin/users").status_code == 403
    assert victim_client.get("/api/v1/admin/overview").status_code == 403


def test_admin_routes_reject_anonymous_callers(anon):
    assert anon.get("/api/v1/admin/users").status_code == 401


def test_estate_overview_counts_the_platforms(admin):
    body = admin.get("/api/v1/admin/overview").json()
    assert body["users"]["total"] >= 1
    assert {p["slug"] for p in body["platforms"]} == {"terminal", "xterminal", "intelligence"}
