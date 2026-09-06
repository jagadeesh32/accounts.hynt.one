# accounts.hynt.one

The single identity provider for Terminal, X-Terminal and Intelligence.

One account, one password, one sign-in. Open any platform and you are already
signed in; sign out once and you are signed out everywhere. Roles, permissions
and pricing plans are held here, per platform, and travel to each platform
inside the access token.

Built on **Cello** (the Rust-powered Python framework), **PostgreSQL** via
SQLAlchemy + Alembic, and **React + Vite + TypeScript**.

---

## How it works

```
  Browser                accounts.hynt.one              terminal.hynt.one
     │                          │                              │
     │  1. open terminal ───────────────────────────────────────▶
     │                          │                              │
     │  ◀── 2. redirect to /oauth/authorize (PKCE) ─────────────┤
     │                          │                              │
     ├── 3. GET /oauth/authorize ▶                              │
     │       (hynt_sso cookie on .hynt.one)                     │
     │                          │                              │
     │       no cookie ──▶ login page ──▶ cookie set            │
     │                          │                              │
     │  ◀── 4. redirect back with a 60-second code ─────────────│
     │                          │                              │
     ├── 5. POST /oauth/token (code + PKCE verifier) ──────────▶│
     │  ◀── 6. RS256 access token, aud=terminal, 15 minutes ────┤
     │                          │                              │
     │  7. requests with Bearer token ─────────────────────────▶│
     │                          │        verifies locally ─────┤
     │                          │        against cached JWKS    │
```

**Nothing calls back to this service on the request path.** Each platform
fetches the JWKS once, caches it, and verifies signatures locally. That is what
makes the estate scale — and the reason the revocation list below exists.

### The cookie

One cookie, `hynt_sso`, on `.hynt.one`. HttpOnly, Secure, SameSite=Lax. It holds
an opaque session id whose SHA-256 is what the database stores, so a dump of the
session table cannot be replayed as a login.

It is deliberately *not* a JWT: this is the thing that has to be revocable the
instant an account is suspended, and a row is revocable by definition.

> Cello stores response headers in a `HashMap`, so a response carries exactly one
> `Set-Cookie`. The design uses a single cookie for that reason, with access
> tokens returned in the body instead of the usual access+refresh cookie pair.

### Tokens

Access tokens are RS256, audience-scoped to one platform, and live 15 minutes.
A token minted for `terminal` is refused by X-Terminal — a leak cannot be
replayed sideways across the estate.

The token carries what a platform needs to authorise a request without asking:

```json
{
  "iss": "https://accounts.hynt.one", "sub": "…", "aud": "terminal",
  "role": "admin", "rank": 30,
  "perms": ["terminal:scanner.run", "terminal:broker.manage"],
  "plan": "pro", "plan_status": "active",
  "ent": ["terminal.intraday", "terminal.smc"],
  "lim": {"scans_per_day": 1000},
  "tv": 3, "sid": "…"
}
```

### Renewal, without refresh tokens in the browser

The SPAs never hold a refresh token. When the 15 minutes are nearly up, a hidden
iframe hits `/oauth/authorize?prompt=none`, which succeeds against the SSO cookie
and returns a fresh code. A page reload does the same thing before rendering.

No long-lived credential is ever stored in `localStorage`.

### Revoking access, immediately

Local verification means a token stays cryptographically valid until it expires.
To make "revoke now" mean now, every revocation is published at
`GET /api/v1/revocations`, which each platform polls every ~30 seconds and
caches. A suspended account stops working within seconds, not fifteen minutes,
and it still costs one small cached request per platform rather than a lookup
per user request.

---

## Roles and plans

Authority is the triple **(user, platform, role)** — one `memberships` row. The
same person can be an admin on Terminal and a plain user on Intelligence.

| Role | Rank | Meaning |
|---|---|---|
| `superadmin` | 40 | Runs the identity provider itself. Above every platform. |
| `admin` | 30 | Full control of one platform, its members and its plans. |
| `staff` | 20 | Operates the platform; cannot change users, roles or billing. |
| `user` | 10 | Standard access, bounded by the subscribed plan. |

Roles bundle **permissions** (`terminal:broker.manage`). Plans grant
**entitlements** (`terminal.intraday`) and **limits** (`scans_per_day`). Access
is the intersection: a platform admin on the free tier still does not get the
paid feature.

A platform admin cannot grant a role above their own — otherwise "admin of
Terminal" would really mean "superadmin, eventually".

---

## Running locally

```bash
./scripts/dev.sh all      # everything, on fixed ports
```

Then http://localhost:5170. Full walkthrough, including the localhost cookie
trick that makes dev SSO work, in [docs/RUNNING_LOCALLY.md](docs/RUNNING_LOCALLY.md).

## Getting started

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then edit HYNT_DATABASE_URL

createdb hynt_accounts
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.manage bootstrap    # seeds platforms, roles, plans, clients + prints the superadmin password
.venv/bin/python -m app.main                    # http://127.0.0.1:9000
```

```bash
cd frontend && npm install && npm run dev       # http://localhost:5173
```

The Vite dev server proxies `/api`, `/oauth` and `/.well-known` to the backend so
the app is same-origin — on `localhost` there is no parent domain to share a
cookie across, so the proxy is what makes the cookie work at all.

### The CLI

```bash
python -m scripts.manage bootstrap                                   # seed / re-seed
python -m scripts.manage create-user --email a@b.c --platform terminal --role admin
python -m scripts.manage grant --email a@b.c --platform xterminal --role staff
python -m scripts.manage passwd --email a@b.c                        # also ends every session
python -m scripts.manage list-clients
python -m scripts.manage rotate-key                                  # old public key stays published
python -m scripts.manage jwks
```

`bootstrap` is idempotent — re-running it re-applies the role/permission/plan
definitions in `scripts/manage.py`, so tightening a role there takes effect on
the next run.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest
```

52 tests, run against a real server on a throwaway database — Cello's HTTP
engine, routing and JSON are all Rust, so anything bypassing the server would be
testing a different code path from the one that serves traffic.

---

## Layout

```
backend/
  app/
    api/         auth · oauth · me · admin · superadmin · public
    core/        security · keys · tokens · sessions · authz · throttle · audit · http
    models/      identity · rbac · billing · oauth
    services/    provisioning · revocation
  alembic/       migrations
  scripts/       manage.py
  tests/
frontend/        the accounts SPA (login, launcher, security, admin console)
packages/
  hynt-sso-python/   FastAPI SDK for the platform backends
  hynt-sso-web/      browser SDK for the platform SPAs
deploy/          nginx
docs/            RUNNING_LOCALLY.md · INTEGRATION.md · DEPLOYMENT.md
```
