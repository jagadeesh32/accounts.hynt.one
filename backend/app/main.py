"""accounts.hynt.one — the Hynt identity provider.

Run:
    python -m app.main
"""

from __future__ import annotations

import logging

from cello import App

from app import config
from app.api import admin, auth, me, oauth, public, superadmin

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-14s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hynt.main")

app = App()

# Cross-origin reads from the three platform SPAs. Cello's CORS middleware
# cannot advertise Allow-Credentials from Python, which suits this design: the
# SSO cookie is only ever sent on same-origin navigations to this host, and the
# token endpoint is authenticated by PKCE rather than by cookie.
app.enable_cors(config.CORS_ORIGINS)
app.enable_compression()
if config.DEBUG:
    app.enable_logging()

# Sync handlers hold a database connection, so they are the blocking kind.
# Cello times them and moves them onto its bounded threadpool once observed to
# block; the pool is sized here so a burst of logins (Argon2 is deliberately
# slow) cannot starve the accept loop.
try:
    from cello import ThreadPoolConfig

    app.set_threadpool(ThreadPoolConfig(size=64, offload_threshold_ms=1, adaptive=True))
except Exception:  # noqa: BLE001 — older builds without the knob still work
    log.debug("threadpool tuning unavailable in this Cello build")

app.register_blueprint(public.bp)
app.register_blueprint(auth.bp)
app.register_blueprint(me.bp)
app.register_blueprint(admin.bp)
app.register_blueprint(superadmin.bp)
app.register_blueprint(superadmin.public_bp)
app.register_blueprint(oauth.bp)
app.register_blueprint(oauth.well_known)


@app.on_event("startup")
def on_startup():
    """Fail loudly at boot rather than on the first login.

    A missing database or an unusable signing key makes every request fail; that
    should be visible in the startup logs, not discovered by a user.
    """
    from app.core import keys
    from app.db import session_scope

    with session_scope() as db:
        key = keys.ensure_key(db)
    log.info("signing key %s active (%s)", key.kid, config.JWT_ALG)
    log.info("issuer   %s", config.ISSUER)
    log.info("cookie   %s domain=%s secure=%s",
             config.COOKIE_NAME, config.COOKIE_DOMAIN or "(host-only)", config.COOKIE_SECURE)


@app.get("/")
def root(request):
    return {
        "service": "accounts.hynt.one",
        "issuer": config.ISSUER,
        "discovery": "/.well-known/openid-configuration",
    }


def main() -> None:
    app.run(
        host=config.HOST,
        port=config.PORT,
        env="production" if config.IS_PROD else "development",
        workers=config.WORKERS,
    )


if __name__ == "__main__":
    main()
