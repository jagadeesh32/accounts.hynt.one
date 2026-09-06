"""Session endpoints for the accounts UI itself.

These are same-origin calls from the accounts.hynt.one SPA. The platforms never
call them — they go through /oauth. The split matters: this is the only surface
that reads or writes the SSO cookie.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from cello import Blueprint
from sqlalchemy import select

from app import config
from app.core import audit, sessions, throttle
from app.core.authz import authenticated
from app.core.http import (
    body_json,
    build_cookie,
    client_ip,
    endpoint,
    field,
    forbidden,
    ok,
    too_many,
    unauthorized,
    user_agent,
    with_cookie,
)
from app.core.security import hash_password, needs_rehash, new_secret, token_digest, verify_password
from app.db import independent_scope
from app.models import (
    Membership,
    Organization,
    PasswordReset,
    Subscription,
    User,
    UserStatus,
)
from app.schemas.serializers import access_entry, session_public, user_public

log = logging.getLogger("hynt.auth")

bp = Blueprint("/api/v1/auth")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 10


def _normalise_email(raw: str) -> str:
    return raw.strip().lower()


def _validate_password(password: str) -> None:
    from app.core.http import bad_request

    if len(password or "") < MIN_PASSWORD_LEN:
        raise bad_request(f"Password must be at least {MIN_PASSWORD_LEN} characters.")


def _access_payload(db, user: User) -> list[dict]:
    """Every platform this user can reach, with role and plan."""
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == user.id, Membership.active.is_(True))
    ).all()
    subs = {
        s.platform_id: s
        for s in db.scalars(select(Subscription).where(Subscription.user_id == user.id))
    }
    entries = [access_entry(m, subs.get(m.platform_id)) for m in memberships]
    entries.sort(key=lambda e: e["platform"]["sort_order"])
    return entries


def _record_rejection(action: str, *, email: str | None, ip: str | None, agent: str | None,
                      user_id=None, count_failure: bool = True, **meta) -> None:
    """Persist the throttle counter and the audit entry for a request that is
    about to be rejected.

    These must not share the request's transaction. The handler raises straight
    after calling this, and that rollback would take the counter and the audit
    row with it — which is exactly what made the lockout never fire and left the
    audit log recording only successful sign-ins.
    """
    with independent_scope() as db:
        if count_failure:
            throttle.record_failure(db, email, ip)
        audit.record(db, action, actor_user_id=user_id, ip=ip, agent=agent,
                     email=email, **meta)


# --------------------------------------------------------------------------- #
#  Login / logout
# --------------------------------------------------------------------------- #
@bp.post("/login")
@endpoint
def login(request, db):
    """Verify credentials and open the SSO session.

    Returns the user and their platform access, not a token. Tokens are minted
    per platform through the OAuth flow, so this response is useful to the
    accounts UI and useless to anyone trying to shortcut the flow.
    """
    data = body_json(request)
    email = _normalise_email(field(data, "email"))
    password = field(data, "password")
    ip, agent = client_ip(request), user_agent(request)

    wait = throttle.check(db, email, ip)
    if wait:
        # Not counted as another failure: a caller who is already locked out
        # would otherwise extend their own lockout just by retrying, turning a
        # 15-minute penalty into a permanent one.
        _record_rejection(audit.LOGIN_THROTTLED, email=email, ip=ip, agent=agent,
                          count_failure=False)
        minutes = max(1, round(wait / 60))
        raise too_many(f"Too many failed attempts. Try again in about {minutes} minute(s).", wait)

    user = db.scalar(select(User).where(User.email == email))
    # verify_password spends the same work on a missing user as on a real one,
    # so the timing of this branch does not answer "does this account exist".
    valid = verify_password(password, user.password_hash if user else None)

    if user is None or not valid:
        _record_rejection(audit.LOGIN_FAILED, email=email, ip=ip, agent=agent,
                          user_id=user.id if user else None)
        raise unauthorized("Invalid email or password.", code="invalid_credentials")

    if user.status == UserStatus.SUSPENDED:
        # A correct password on a suspended account is not a brute-force attempt,
        # so it is audited without counting toward the lockout.
        _record_rejection(audit.LOGIN_FAILED, email=email, ip=ip, agent=agent,
                          user_id=user.id, count_failure=False, reason="suspended")
        raise forbidden("This account has been suspended. Contact an administrator.",
                        code="account_suspended")
    if user.status == UserStatus.PENDING:
        raise forbidden("Finish setting up your account from the invitation email first.",
                        code="account_pending")

    # Upgrade the stored hash opportunistically when the cost parameters have
    # been raised since the password was last set.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    throttle.clear(db, email, ip)
    user.last_login_at = datetime.now(timezone.utc)

    row, raw = sessions.create(db, user, ip=ip, agent=agent)
    audit.record(db, audit.LOGIN_SUCCESS, actor_user_id=user.id, ip=ip, agent=agent,
                 session_id=row.id)

    response = ok(
        {
            "user": user_public(user),
            "access": _access_payload(db, user),
            "session_id": str(row.id),
        }
    )
    return with_cookie(response, build_cookie(config.COOKIE_NAME, raw,
                                              max_age=config.SESSION_TTL_SEC))


@bp.post("/logout")
@endpoint
def logout(request, db):
    """End the SSO session and clear the cookie.

    Deliberately succeeds even without a valid session: a logout button that can
    return an error is a logout button that sometimes leaves people signed in.
    """
    from app.core.authz import current_context

    ctx = current_context(request, db)
    if ctx is not None:
        sessions.revoke(db, ctx.session)
        audit.record(db, audit.LOGOUT, actor_user_id=ctx.user.id, ip=ctx.ip, agent=ctx.agent,
                     session_id=ctx.session.id)

    response = ok({"ok": True})
    return with_cookie(response, build_cookie(config.COOKIE_NAME, "", max_age=0, delete=True))


@bp.get("/session")
@endpoint
def session_info(request, db):
    """Is there a live SSO session? Answers 200 with ``authenticated: false``
    rather than 401, because "not signed in" is the expected answer here and the
    SPA should not treat it as an error."""
    from app.core.authz import current_context

    ctx = current_context(request, db)
    if ctx is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": user_public(ctx.user),
        "access": _access_payload(db, ctx.user),
        "session": session_public(ctx.session, current_id=ctx.session.id),
    }


# --------------------------------------------------------------------------- #
#  Registration
# --------------------------------------------------------------------------- #
@bp.post("/register")
@endpoint
def register(request, db):
    """Self-service signup, off by default.

    All three platforms disabled self-registration independently; the switch now
    lives in one place. A new account lands with an org of its own and the
    default role on every platform that has one, which is what makes a signup
    immediately useful instead of a support ticket.
    """
    from app.core.http import bad_request, conflict

    if not config.ALLOW_SELF_REGISTRATION:
        raise forbidden("Self-registration is disabled. Contact an administrator.",
                        code="registration_disabled")

    data = body_json(request)
    email = _normalise_email(field(data, "email"))
    password = field(data, "password")
    full_name = (data.get("full_name") or "").strip()

    if not _EMAIL_RE.match(email):
        raise bad_request("Enter a valid email address.")
    _validate_password(password)

    if db.scalar(select(User).where(User.email == email)) is not None:
        raise conflict("An account with that email already exists.", code="email_taken")

    from app.services.provisioning import create_user_account

    user = create_user_account(db, email=email, password=password, full_name=full_name)
    ip, agent = client_ip(request), user_agent(request)
    row, raw = sessions.create(db, user, ip=ip, agent=agent)
    audit.record(db, audit.USER_CREATED, actor_user_id=user.id, target_type="user",
                 target_id=user.id, ip=ip, agent=agent, self_service=True)

    response = ok({"user": user_public(user), "access": _access_payload(db, user)}, status=201)
    return with_cookie(response, build_cookie(config.COOKIE_NAME, raw,
                                              max_age=config.SESSION_TTL_SEC))


# --------------------------------------------------------------------------- #
#  Passwords
# --------------------------------------------------------------------------- #
@bp.post("/password/change")
@authenticated
def change_password(request, db, ctx):
    """Change the password, then end every other session.

    The current session is kept so the user is not bounced to the login screen by
    their own action; everything else dies, because "I think someone has my
    password" is the main reason anyone changes one.
    """
    from app.core.http import bad_request

    data = body_json(request)
    current = field(data, "current_password")
    new = field(data, "new_password")

    if not verify_password(current, ctx.user.password_hash):
        raise forbidden("Your current password is incorrect.", code="wrong_password")
    _validate_password(new)
    if verify_password(new, ctx.user.password_hash):
        raise bad_request("The new password must be different from the current one.")

    ctx.user.password_hash = hash_password(new)
    ctx.user.token_version += 1     # every access token minted so far stops verifying
    revoked = sessions.revoke_all_for_user(db, ctx.user.id, except_session_id=ctx.session.id)

    audit.record(db, audit.PASSWORD_CHANGED, actor_user_id=ctx.user.id, ip=ctx.ip,
                 agent=ctx.agent, sessions_revoked=revoked)
    return {"ok": True, "sessions_revoked": revoked}


@bp.post("/password/forgot")
@endpoint
def forgot_password(request, db):
    """Always answers the same way, whether or not the address is known.

    In development the token comes back in the response so the flow is testable
    without a mail server; in production it must be emailed instead.
    """
    data = body_json(request)
    email = _normalise_email(field(data, "email"))
    ip, agent = client_ip(request), user_agent(request)

    # Rate-limited on IP alone: without it this endpoint is both a mail flood and
    # an account enumerator driven by response timing.
    wait = throttle.check(db, None, ip)
    if wait:
        raise too_many("Too many requests. Try again shortly.", wait)
    throttle.record_failure(db, None, ip)

    generic = {"ok": True, "message": "If that account exists, a reset link has been sent."}
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.status == UserStatus.SUSPENDED:
        return generic

    raw = new_secret(32)
    now = datetime.now(timezone.utc)
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=token_digest(raw),
            expires_at=now + timedelta(seconds=config.PASSWORD_RESET_TTL_SEC),
            created_at=now,
        )
    )
    audit.record(db, audit.PASSWORD_RESET_REQUESTED, actor_user_id=user.id, ip=ip, agent=agent)
    log.info("password reset requested for %s", user.email)

    if config.DEBUG:
        generic["reset_token"] = raw
    return generic


@bp.post("/password/reset")
@endpoint
def reset_password(request, db):
    """Consume a reset token and set a new password.

    Succeeding here ends every session the account had — the point of a reset is
    that whoever else was signed in should not stay signed in.
    """
    from app.core.http import bad_request

    data = body_json(request)
    raw = field(data, "token")
    new = field(data, "password")
    ip, agent = client_ip(request), user_agent(request)

    wait = throttle.check(db, None, ip)
    if wait:
        raise too_many("Too many requests. Try again shortly.", wait)

    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_digest(raw)))
    now = datetime.now(timezone.utc)
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row and not row.expires_at.tzinfo \
        else (row.expires_at if row else None)

    if row is None or row.used_at is not None or expires <= now:
        # Counted, and committed independently — otherwise reset tokens could be
        # guessed without limit for the same reason passwords could.
        _record_rejection(audit.PASSWORD_RESET_REQUESTED, email=None, ip=ip, agent=agent,
                          outcome="invalid_token")
        raise bad_request("That reset link is invalid or has expired.", code="invalid_token")

    _validate_password(new)

    user = db.get(User, row.user_id)
    if user is None:
        raise bad_request("That reset link is invalid or has expired.", code="invalid_token")

    user.password_hash = hash_password(new)
    user.token_version += 1
    # A reset is also how an invited user activates, so clear PENDING here.
    if user.status == UserStatus.PENDING:
        user.status = UserStatus.ACTIVE
    row.used_at = now
    revoked = sessions.revoke_all_for_user(db, user.id)

    audit.record(db, audit.PASSWORD_RESET_COMPLETED, actor_user_id=user.id, ip=ip, agent=agent,
                 sessions_revoked=revoked)
    return {"ok": True, "message": "Password updated. You can sign in now."}
