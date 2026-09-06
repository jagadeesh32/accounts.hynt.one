"""accounts.hynt.one — the Hynt identity provider.

Served by Uvicorn on 127.0.0.1:8103 behind nginx (see deploy/nginx.conf), which
also serves the built SPA from /var/www/accounts.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, analytics, auth, me, oauth, public, superadmin
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("hynt.accounts")

app = FastAPI(
    title="Hynt Accounts",
    description="One account for Terminal, X-Terminal and Intelligence.",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# The platform SPAs *do* call this API directly: @hynt/sso-web redirects here to
# authorize, but exchanges the resulting code with a cross-origin JSON fetch to
# /oauth/token. That preflights, so without an origin list the browser blocks the
# exchange and sign-in fails as "Failed to fetch" — server-side flows still pass,
# which is what makes it easy to miss. Set HYNT_CORS_ORIGINS in every environment.
if settings.cors_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(superadmin.router)
# Aggregates for both consoles: the estate-wide board (superadmin) and the
# per-platform one (gated on rank, same as the rest of app.api.admin).
app.include_router(analytics.router)
app.include_router(analytics.platform_router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never leak a stack trace to a browser at an auth endpoint.
    log.exception("unhandled error at %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal error"}, status_code=500)


@app.on_event("startup")
async def startup():
    from app.core.keys import get_active_key
    from app.db import SessionLocal

    async with SessionLocal() as db:
        key = await get_active_key(db)
        log.info("issuer=%s signing kid=%s", settings.issuer, key.kid)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=9000, reload=True)
