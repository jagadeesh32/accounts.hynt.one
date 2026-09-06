# Integrating a platform

What was done to Terminal, X-Terminal and Intelligence — and what to do for a
fourth platform.

The guiding constraint: **no route handler changed.** All three platforms keep
their existing dependency names (`current_user`, `require_admin`, `require_role`,
`CurrentUser`, `OwnerUser`) and their existing return shapes. Only what sits
underneath them changed. That is 188 call sites left untouched.

---

## The shadow-user pattern

Each platform keeps its own `users` row. It has to: positions, alerts, watchlists,
documents and MCP keys all reference that row's id, and in Intelligence's case
the entire corpus is scoped by the org it belongs to.

So the local row becomes a **projection** of the central account rather than the
authority on it, linked by a nullable `sso_subject` column:

1. **Already linked** — one indexed lookup. The common path.
2. **Known email, not yet linked** — an account predating SSO. The subject is
   stamped onto the existing row, so all of its data stays attached.
3. **Unknown** — a user granted access centrally who has never opened this app.
   The row is created. accounts.hynt.one has already decided they may be here;
   refusing would only produce a support ticket.

Name and role are re-synced from the token on every request, so a demotion made
centrally lands here on the next request rather than at the next manual edit.

**No data was migrated and no local id changed.** Existing users keep everything.

---

## Backend

```bash
pip install -e /path/to/accounts.hynt.one/packages/hynt-sso-python
```

```python
from hynt_sso import HyntSSO

sso = HyntSSO(
    issuer="https://accounts.hynt.one",
    audience="terminal",        # this platform's slug = the JWT audience
    check_revocations=True,     # poll the revocation list; on by default
)
```

Then resolve a bearer token to a principal:

```python
principal = sso.principal(token)      # raises TokenError
principal = sso.principal_or_none(token)   # for WebSocket upgrades

principal.has_role("admin")
principal.has_permission("terminal:broker.manage")
principal.has_entitlement("terminal.intraday")
principal.limit("scans_per_day", 25)
```

FastAPI dependencies are provided directly:

```python
from hynt_sso.fastapi import build_dependencies

current_user, require_role, require_permission = build_dependencies(sso)

@router.post("/broker/connect")
def connect(user = Depends(require_permission("terminal:broker.manage"))):
    ...
```

Prefer `require_permission` over `require_role` for new routes: it states what
the route needs, so tightening a role centrally does not mean auditing every
role comparison in the codebase.

`require_entitlement` answers **402**, not 403 — the caller is allowed to do
this, they simply have not paid for it, and the UI should offer an upgrade
rather than an error.

### What each platform actually got

| | Terminal | X-Terminal | Intelligence |
|---|---|---|---|
| Local store | MariaDB | SQLite | PostgreSQL |
| Local id | `INTEGER` | `INTEGER` | `UUID` |
| Link column | `users.sso_subject` | `users.sso_subject` | `users.sso_subject` |
| Migration | `m4n5o6p7q8r9` | `_COLUMN_MIGRATIONS` | `e2a5b8d31f04` |
| Central role → local | admin/staff → `admin` | admin+ → `admin` | admin+ → `owner` |
| Enforcement | middleware + deps | deps | deps |

Removed from all three: scrypt/PBKDF2 hashing, token minting, HMAC signing,
login throttles, reset-token handling. Four copies of that became one.

Routes that moved (`/auth/login`, `/signup`, `/forgot`, `/reset`,
`/change-password`, `/profile`) answer **410 Gone** with the accounts URL, so a
stale client is told where to go rather than left guessing at a 404.

---

## Frontend

```ts
import { HyntSso, relaySilentCallback } from "@hynt/sso-web";

export const sso = new HyntSso({
  issuer: import.meta.env.VITE_SSO_ISSUER,
  clientId: "terminal-web",
  redirectUri: `${window.location.origin}/auth/callback`,
  postLogoutRedirectUri: `${window.location.origin}/`,
  onSignedOut: () => { /* bounce to the gate */ },
});
```

Three integration points:

```ts
// 1. At startup, before rendering: pick up an existing session silently.
const signedIn = await sso.silentSignIn();

// 2. On /auth/callback. relaySilentCallback() must run first — this window may
//    be the hidden renewal iframe, which must post its result and draw nothing.
if (!relaySilentCallback()) {
  const { returnTo } = await sso.handleCallback();
  window.location.replace(returnTo);
}

// 3. Attach the token to every same-origin /api/ call, with one silent retry
//    on a 401 so a token that expired mid-request is not a visible failure.
sso.installFetchInterceptor("/api/");
```

`sso.signOut()` redirects to the provider's end-session endpoint. Clearing only
the local tab would leave the user signed in to every sibling platform — the
opposite of what a sign-out button means.

The access token is held **in memory only**. A token in `localStorage` outlives
the tab, is readable by any script on the page, and has to be long-lived to be
useful; silent renewal removes the need for all three.

---

## Adding a fourth platform

1. Register it — `POST /api/v1/admin/platforms` (or the admin console). This
   also creates its `admin`/`staff`/`user` roles.
2. Add its permissions and plans to `PLATFORMS` in `backend/scripts/manage.py`
   and re-run `bootstrap`. It is idempotent.
3. Its OAuth client (`<slug>-web`, public, PKCE) is created by the same run.
4. Point its backend at the SDK with `audience="<slug>"`, and its SPA at
   `clientId: "<slug>-web"`.

No change to this service's code is required.
