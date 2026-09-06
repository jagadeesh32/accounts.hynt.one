# Putting a platform behind accounts.hynt.one

Terminal is already wired up; this is what it did, and what X-Terminal and
Intelligence still need.

## 1. Register the client

```bash
cd /opt/accounts.hynt.one/backend
.venv/bin/python -m scripts.manage list-clients
```

`terminal-web`, `xterminal-web` and `intelligence-web` are seeded by `bootstrap`.
Redirect URIs are an **exact** allow-list — add one in `scripts/manage.py` and
re-run `bootstrap`, or use the Estate console.

## 2. Backend — verify tokens locally

```bash
pip install -e /opt/accounts.hynt.one/packages/hynt-sso-python
```

```python
from hynt_sso import HyntSSO, TokenError

sso = HyntSSO(issuer="https://accounts.hynt.one", audience="xterminal")

principal = sso.bearer(request.headers.get("authorization"))
principal.has_role("staff")                      # rank >= staff
principal.has_permission("xterminal:orders.place")
principal.has_entitlement("xterminal.algo")
principal.limit("orders_per_day", 10)
```

`audience` must be the platform slug. A token minted for `terminal` will be
refused here — that is the point, and it means a leak cannot travel sideways.

**Keep your local `users` row.** Positions, alerts and API keys reference its
id. Link on first sign-in by `principal.user_id`, falling back to a match on
email for accounts that predate SSO — see terminal's `app/auth/sso.py`.

## 3. Frontend — redirect, don't prompt

```jsonc
"dependencies": { "@hynt/sso-web": "file:../../accounts.hynt.one/packages/hynt-sso-web" }
```

```ts
import { HyntSso, relaySilentCallback } from "@hynt/sso-web";

export const sso = new HyntSso({
  issuer: "https://accounts.hynt.one",
  clientId: "xterminal-web",
  redirectUri: `${window.location.origin}/auth/callback`,
  postLogoutRedirectUri: `${window.location.origin}/`,
});

await sso.silentSignIn();            // renews against the hynt_sso cookie
sso.installFetchInterceptor("/api/");
```

Add a `/auth/callback` route that calls `relaySilentCallback()` **first** — the
same route is loaded inside the hidden renewal iframe, and that call is what
tells the two cases apart.

Delete the local password form. There is one in the estate and it lives here.

## 4. What the token carries

```json
{
  "iss": "https://accounts.hynt.one", "sub": "…", "aud": "xterminal",
  "role": "admin", "rank": 30,
  "perms": ["xterminal:orders.place"],
  "plan": "pro", "plan_status": "active",
  "ent": ["xterminal.algo"], "lim": {"orders_per_day": 1000},
  "tv": 3, "sid": "…"
}
```

15 minutes, RS256, verified locally against the cached JWKS. Nothing calls back
here on the request path.

## 5. Revocation

Because verification is local, a token stays cryptographically valid until it
expires. `GET /api/v1/revocations` closes that gap: the SDK polls it every ~30s
(one cached request per process, not per user request) and refuses anything
listed. A suspended account stops working in seconds.

The poll **fails open** if this service is unreachable — an outage here must not
become an outage everywhere.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/openid-configuration` | discovery |
| `GET /.well-known/jwks.json` | public keys (cache 1h) |
| `GET /oauth/authorize` | code + PKCE; `prompt=none` for silent renewal |
| `POST /oauth/token` | code → 15-minute access token |
| `GET /oauth/logout` | ends the estate-wide session |
| `GET /api/v1/revocations` | poll every ~30s |
