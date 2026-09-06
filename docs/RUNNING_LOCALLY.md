# Running the estate locally

## TL;DR

```bash
cd /root/hynt/accounts.hynt.one
./scripts/dev.sh all
```

Then open **http://localhost:5170**, sign in as `admin@hynt.one`, and open
Terminal at :5174. It will not ask you again — that is the whole thing working.

`Ctrl-C` stops everything.

---

## The one thing that matters in dev

In production the cookie is set on `.hynt.one`, so every subdomain shares it.
On localhost there is no parent domain to share, so the trick is different:
**cookies ignore the port**. A cookie set on `localhost` is sent from
`localhost:5174` too.

So everything must reach the identity provider on **one host**, and that host is
`http://localhost:5170` — the accounts Vite server, which proxies `/api`,
`/oauth` and `/.well-known` through to the backend on `:9000`.

That is why `HYNT_ISSUER=http://localhost:5170` and not `:9000`. Three places
must agree on it, and a mismatch rejects every token on its `iss` check:

| Where | Setting |
|---|---|
| `accounts.hynt.one/backend/.env` | `HYNT_ISSUER=http://localhost:5170` |
| each platform's `backend/.env` | `HYNT_SSO_ISSUER=http://localhost:5170` |
| each platform's `frontend/.env` | `VITE_SSO_ISSUER=http://localhost:5170` |

Never open the app on `127.0.0.1:5170` — to a browser that is a *different host*
from `localhost`, so the cookie will not be sent and you will be asked to sign
in on a loop. Use `localhost` everywhere.

---

## Ports

Fixed on purpose. The OAuth redirect URI is registered up front, so a dev server
that silently picks the next free port breaks sign-in with an "unregistered
redirect_uri" that looks like a config bug. Every Vite server is `strictPort`.

| | Web | API |
|---|---|---|
| Accounts | **5170** | 9000 |
| Terminal | 5174 | 8000 |
| X-Terminal | 5175 | 8001 |
| Intelligence | 5176 | 8100 |

These were all colliding on 5173/5174 before, so the four could not run at once.

---

## First-time setup

Once per machine.

```bash
# 1. Accounts backend
cd /root/hynt/accounts.hynt.one/backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
createdb hynt_accounts                       # or: sudo -u postgres createdb hynt_accounts
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.manage bootstrap \
    --email admin@hynt.one --password 'Sup3rSecret!2026' --name 'Your Name'

# 2. Accounts frontend
cd ../frontend && npm install

# 3. The SDK into each platform's venv
for p in terminal xterminal intelligence; do
  /root/hynt/$p.hynt.one/backend/.venv/bin/python -m pip install -e \
    /root/hynt/accounts.hynt.one/packages/hynt-sso-python
done

# 4. Each platform's own migration (adds users.sso_subject)
cd /root/hynt/intelligence.hynt.one/backend && .venv/bin/python -m alembic upgrade head
# Terminal runs `alembic upgrade head` itself on startup — nothing to do.
# X-Terminal adds the column via its own _COLUMN_MIGRATIONS on first boot.
```

`bootstrap` is idempotent: re-run it any time to re-apply the platform, role,
permission and plan definitions in `backend/scripts/manage.py`.

---

## Running

```bash
./scripts/dev.sh              # accounts only
./scripts/dev.sh all          # accounts + all three platforms
./scripts/dev.sh terminal     # accounts + one platform

./scripts/dev.sh stop         # free every port this script uses
./scripts/dev.sh all --force  # free them first, then start
```

`Ctrl-C` stops everything and releases all eight ports. If a run is ever left
behind — a killed terminal, a crashed shell — the next start refuses with a list
of which ports are held and by what, rather than a wall of Vite stack traces.
`stop` clears it.

Terminal's API takes ~15s to come up: it runs `alembic upgrade head`, seeds its
engines and arms its scheduler before it binds. The others are up in about two.

Or by hand, one terminal each:

```bash
cd accounts.hynt.one/backend      && .venv/bin/python -m app.main
cd accounts.hynt.one/frontend     && npm run dev
cd terminal.hynt.one/backend      && .venv/bin/python -m uvicorn app.main:app --port 8000
cd terminal.hynt.one/frontend     && npm run dev
cd xterminal.hynt.one/backend     && .venv/bin/python -m uvicorn app.main:app --port 8001
cd xterminal.hynt.one/frontend    && npm run dev
cd intelligence.hynt.one/backend  && .venv/bin/python -m uvicorn app.main:app --port 8100
cd intelligence.hynt.one/frontend && npm run dev
```

> X-Terminal's virtualenv has stale shebangs — it was created at
> `/root/x_terminal/backend/.venv` and moved, so `.venv/bin/pip` is broken.
> Use `.venv/bin/python -m pip`. (Pre-existing; unrelated to SSO.)

---

## Checking it works

```bash
curl -s http://localhost:5170/api/v1/health
curl -s http://localhost:5170/.well-known/openid-configuration | jq .issuer
curl -s http://localhost:5170/.well-known/jwks.json | jq '.keys[0].kid'
curl -s http://localhost:5170/api/v1/revocations
```

In the browser:

1. **http://localhost:5170** → sign in. You land on the launcher with all three
   platforms, each showing your role and plan.
2. Open **http://localhost:5174** in the same browser. No password prompt.
3. Sign out anywhere → all three drop to their sign-in screen on next renewal.

Admin console at **http://localhost:5170/admin/users** → click a user for the
full picture: platform access, devices with IPs, complete activity, and the
revoke/delete controls.

---

## Tests

```bash
cd accounts.hynt.one/backend && .venv/bin/python -m pytest
```

Spins up its own server on `:9111` against a throwaway `hynt_accounts_test`
database, so it never touches your dev data and does not need `dev.sh` running.

---

## When it does not work

**Asked to sign in over and over.** You are on `127.0.0.1` instead of
`localhost`, or `HYNT_ISSUER` disagrees with `VITE_SSO_ISSUER`. Confirm the
`hynt_sso` cookie exists in DevTools → Application → Cookies for `localhost`.

**`invalid_redirect_uri`.** A Vite server took a different port than the one
registered. Check with `python -m scripts.manage list-clients`; the URI must
match exactly, including the port.

**`token is not for '<platform>'`.** `HYNT_SSO_AUDIENCE` does not match the
platform's slug. Terminal is `terminal`, X-Terminal is `xterminal`,
Intelligence is `intelligence`.

**`column users.sso_subject does not exist`.** That platform's migration has not
run — see step 4 of first-time setup.

**Signed out ~15 minutes in.** Silent renewal is failing. It uses a hidden
iframe on `/oauth/authorize`, so check the browser console for a frame-blocked
error and that nothing is sending `X-Frame-Options: DENY` on `:5170`.

**`Port 5170 is already in use`** (or any of the eight). A previous run is still
going. `./scripts/dev.sh stop`, or start with `--force`.

**Locked out after five bad passwords.** Working as intended. Wait 15 minutes,
or clear it:
`psql -d hynt_accounts -c "DELETE FROM login_attempts;"`
