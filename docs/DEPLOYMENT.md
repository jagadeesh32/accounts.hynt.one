# Deploying accounts.hynt.one

What is running on this box, and how to change it.

| Piece | Where |
|---|---|
| Backend | `accounts-hynt.service` → Uvicorn on `127.0.0.1:8103` |
| Frontend | built to `/var/www/accounts`, served by nginx |
| Database | PostgreSQL `hynt_accounts`, owned by role `hynt_accounts` |
| nginx | `deploy/nginx.conf`, symlinked into `sites-enabled` |
| TLS | Let's Encrypt, `accounts.hynt.one`, auto-renewed by certbot |
| Housekeeping | `accounts-hynt-prune.timer`, hourly |

The service file, the nginx config and the timers are **symlinks into this
repo** — `git pull` changes them, `systemctl daemon-reload` applies them. There
is no second copy to drift.

## Deploy a change

```bash
cd /opt/accounts.hynt.one && git pull

# backend
cd backend
.venv/bin/pip install -r requirements.txt      # only if requirements moved
.venv/bin/alembic upgrade head                 # only if models moved
systemctl restart accounts-hynt

# frontend
cd ../frontend && npm ci && npm run build
rm -rf /var/www/accounts/* && cp -r dist/* /var/www/accounts/
```

Config changes (`deploy/*.service`, `deploy/nginx.conf`):

```bash
systemctl daemon-reload && systemctl restart accounts-hynt
nginx -t && systemctl reload nginx
```

## Checks

```bash
systemctl status accounts-hynt
journalctl -u accounts-hynt -f
curl -s https://accounts.hynt.one/api/v1/health
curl -s https://accounts.hynt.one/.well-known/jwks.json
```

## Secrets

`backend/.env` (mode 600, gitignored) holds the database URL. The RSA signing
keys are **rows in the database**, not files — so every worker signs with the
same key and rotation is one transaction. Back up the database and you have
backed up the keys.

## Two things that will bite

**`--workers 2` is safe here** — this service keeps no per-process state, unlike
terminal, which must stay at 1. The only in-memory thing is the login throttle,
which is per-worker: the effective login limit is `workers × limit`.

**Rotating a key is not instant.** Platforms cache the JWKS for an hour, so a
freshly rotated key cannot verify anywhere until they refresh. The old public
key stays published for exactly this reason — rotation never signs anyone out.

## Restore an account after the SSO migration

Local password login was retired in the three platform databases on 2026-09-06
(hashes replaced with the sentinel `!sso`). The pre-change rows are dumped in
`var/legacy-backup/`. Identity now lives only in `hynt_accounts`:

```bash
cd backend
.venv/bin/python -m scripts.manage list-users
.venv/bin/python -m scripts.manage passwd --email someone@example.com
```
