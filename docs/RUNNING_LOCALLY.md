# Running locally

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then set HYNT_DATABASE_URL

createdb hynt_accounts
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.manage bootstrap    # prints the superadmin password
.venv/bin/python -m app.main                    # http://127.0.0.1:9000
```

```bash
cd frontend && npm install && npm run dev       # http://localhost:5170
```

## The localhost cookie trick

The SSO cookie is set on `.hynt.one`. On `localhost` there is no parent domain
to share it across, so:

* the Vite dev server **proxies** `/api`, `/oauth` and `/.well-known` to the
  backend, which makes the app same-origin — that proxy is what makes the cookie
  work at all in dev; and
* the cookie must be host-only and insecure locally:

```bash
HYNT_COOKIE_DOMAIN=
HYNT_COOKIE_SECURE=false
```

Leave `HYNT_COOKIE_SECURE=true` and the browser silently drops the cookie on
plain HTTP — you sign in, get a 200, and are still signed out. That symptom is
almost always this setting.

## Testing a platform against local accounts

`bootstrap` registers `http://localhost:5173/auth/callback` (and 5174, 5175) as
redirect URIs, so a platform dev server can point at a local IdP without a
second client.

## Tests

```bash
cd backend && .venv/bin/python -m pytest
```

28 tests against a real server on a throwaway database (`hynt_accounts_test`,
dropped and recreated each run — the role needs `CREATEDB`). Nothing bypasses
the HTTP layer: the cookie handling and the redirect behaviour are where the
risk in this service lives, and only a real request exercises them.
