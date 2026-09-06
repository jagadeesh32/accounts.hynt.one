# Deployment & cutover

## DNS and TLS

`accounts.hynt.one` must be a sibling of the platform hosts under `hynt.one`.
The SSO cookie is set on `.hynt.one`; a different registrable domain cannot
share it and single sign-on will not happen.

## nginx

`deploy/nginx-accounts.conf` and `deploy/hynt-proxy-params.conf`. Two settings
there are load-bearing:

**`X-Forwarded-For`.** Cello reads the client address from this header and
nowhere else. Without it every session row and audit entry records a null IP —
the "where was this account signed in from" screen is blank, and the login
throttle degrades to per-email only, which lets one attacker lock a real user
out of their own account from anywhere.

**`frame-ancestors` on `/oauth/`.** The silent-renewal iframe on each platform
loads `/oauth/authorize` from this host. If the whole host is `X-Frame-Options:
DENY`, renewal fails everywhere and users are bounced to the login page every
fifteen minutes.

## Signing key

Generate and pin one before the first production boot:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out /etc/hynt/signing.pem
chmod 600 /etc/hynt/signing.pem
# HYNT_SIGNING_KEY_PATH=/etc/hynt/signing.pem
```

Left unset, a key is generated into the database on first boot. That is fine in
development, but a redeploy onto an empty database then silently invalidates
every live session across all three platforms.

Rotate with `python -m scripts.manage rotate-key`. The previous public key stays
published until the tokens it signed have expired, so rotation is invisible.

## Cutover runbook

The platforms can be migrated one at a time — each is independent.

1. **Deploy accounts.hynt.one.** Migrate, bootstrap, verify
   `/.well-known/openid-configuration` and `/.well-known/jwks.json`.

2. **Import the existing users.** Accounts are matched by email on first
   sign-in, so create each existing user centrally with the same address:

   ```bash
   python -m scripts.manage create-user --email trader@example.com --name "…"
   python -m scripts.manage grant --email trader@example.com --platform terminal --role user
   ```

   Passwords cannot be carried across — the three platforms used three different
   hash schemes, and Argon2 cannot be derived from any of them. Use `--invite`
   to create the account with no usable password and print a single-use,
   seven-day activation link:

   ```bash
   python -m scripts.manage create-user --email trader@example.com --name "…" --invite
   ```

   That is the invitation flow, rather than an administrator inventing a
   password and sending it over chat.

3. **Per platform, in order:**
   - Run its migration (`alembic upgrade head`, or restart for X-Terminal, whose
     column migrations run at import).
   - Set `HYNT_SSO_ISSUER`, `HYNT_SSO_AUDIENCE`, `HYNT_ACCOUNT_URL`.
   - Set `VITE_SSO_ISSUER` and `VITE_SSO_CLIENT_ID`, rebuild the SPA.
   - Add `/auth/callback` to the SPA fallback in nginx.
   - Deploy. Existing rows link themselves to the central account on first
     sign-in.

4. **Verify** on each platform: sign in, confirm the local row got its
   `sso_subject`, confirm a token from a sibling platform is refused.

### Rollback

Each platform's previous auth module is one file (`app/api/auth.py`,
`app/auth/routes.py` + `deps.py`). Reverting that file and redeploying restores
local login; the `sso_subject` column is nullable and additive, so it can stay.

## Pre-existing issues found on the way

Not caused by this work, but they will bite:

- **Terminal's database is 4 migrations behind** its own `alembic/versions/`
  (`h9i0j1k2l3m4` vs `l3m4n5o6p7q8`). My migration chains after those, so
  `alembic upgrade head` applies all five. Review the four first.
- **Intelligence's database is 1 migration behind** (`b4e8c2a19f70` vs
  `d1f4a7c20e93`), same situation.
- **X-Terminal's virtualenv has stale shebangs** — it was created at
  `/root/x_terminal/backend/.venv` and moved, so `.venv/bin/pip` is broken. Use
  `.venv/bin/python -m pip`, or recreate the venv.

Both migration gaps were verified on throwaway copies of the real databases
rather than against production data.

## Operations

- `GET /api/v1/health` — liveness with a real database round-trip. A health
  check that does not touch the database reports green while every request 500s.
- `GET /api/v1/revocations` — what the platforms poll. Watch it: if it starts
  erroring, revocations stop landing (the SDK fails open by default, which keeps
  a provider blip from signing everyone out).
- `GET /api/v1/admin/overview` — users, live sessions, 24h sign-ins and failures.
- `GET /api/v1/admin/audit` — the full trail.
