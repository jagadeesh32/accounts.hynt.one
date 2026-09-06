# Roles, plans and the console

Who can do what across the estate, what each plan grants, and which of that the
accounts console exposes.

Captured 2026-09-06 from the live `hynt_accounts` database. The tables below are
data, not configuration — the console is the place to change them, and this file
will drift the moment you do.

## The shape of it

Authority is split in two, deliberately:

| Question | Answered by | Where it lives |
|---|---|---|
| Are you an operator of the identity provider itself? | `users.is_superadmin` | one boolean per account |
| What may you do on Terminal / X-Terminal / Intelligence? | a **role** per platform | `memberships` → `roles` |
| What features has your subscription bought? | a **plan** per platform | `subscriptions` → `plans` |

Role and plan are independent. An `admin` on the free plan administers a
platform whose features are capped; a `user` on pro has every feature and no
authority over anyone else. Do not use one to imply the other.

## accounts.hynt.one has no roles and no plans

It is the identity provider, not a product. There is nothing to subscribe to and
no per-platform ladder to sit on, so access is the single `is_superadmin` flag.

| Account | Name | Superadmin | 2FA | Status |
|---|---|---|---|---|
| `admin@hynt.one` | Hynt Superadmin | yes | off | active |
| `katla.jagadeesh@gmail.com` | Jagadeesh Katla | yes | off | active |

A superadmin can administer every platform, every account and the signing keys.
The last one cannot remove their own flag — `POST /superadmin/users/{id}/superadmin`
refuses it, because an estate with no superadmin has locked itself out for good.

Changing the flag **revokes that user's tokens estate-wide within seconds**, so
the new authority (or its absence) takes effect immediately rather than at the
next token expiry.

## Roles

The same three-tier ladder on each platform. `rank` is the whole authorisation
model: you may only grant a role whose rank is at or below your own, which is
what stops a staff member promoting themselves.

| Platform | Role | Name | Rank | Permissions |
|---|---|---|---|---|
| **terminal** | `admin` | Administrator | 30 | `scanner.run`, `broker.manage`, `positions.sync`, `alerts.manage`, `members.manage`, `billing.manage` |
| | `staff` | Staff | 20 | `scanner.run`, `broker.manage`, `positions.sync`, `alerts.manage` |
| | `user` | Member | 10 | `scanner.run`, `alerts.manage` |
| **xterminal** | `admin` | Administrator | 30 | `orders.place`, `strategies.manage`, `members.manage`, `billing.manage` |
| | `staff` | Staff | 20 | `orders.place`, `strategies.manage` |
| | `user` | Member | 10 | `orders.place` |
| **intelligence** | `admin` | Administrator | 30 | `documents.manage`, `entities.manage`, `members.manage`, `billing.manage` |
| | `staff` | Staff | 20 | `documents.manage`, `entities.manage` |
| | `user` | Member | 10 | `documents.read` |

Permissions are stored fully namespaced (`terminal:scanner.run`); the prefix is
elided above for width. The namespace is not decoration — it is why a token
minted for one platform cannot be read as authority on another.

Note the ladder is not uniform in meaning. On Intelligence a plain member can
only *read* documents, while on X-Terminal a plain member can *place orders*.
Grant `user` on X-Terminal with that in mind.

### How a role reaches a desk

The role slug and its permissions are copied into the access token as the `role`
and `perms` claims at mint time. A desk checks them locally and never calls back
here, so **a role change reaches a desk on that member's next token — up to 15
minutes.** Suspension and the superadmin flag are the exceptions: both publish a
revocation, which desks poll every ~30 seconds.

Each desk maps the central role onto its own vocabulary. Intelligence, for
example, treats central `staff` as local `owner` (see `app/auth/sso.py`), so
"who can run a backfill there" is a question about that mapping, not about this
table.

## Plans

| Platform | Plan | Price | Default | Entitlements | Limits |
|---|---|---|---|---|---|
| **terminal** | `free` | ₹0/month | yes | `terminal.eod` | 5 alerts, 25 scans/day |
| | `pro` | ₹1,499/month | | `terminal.eod`, `terminal.intraday`, `terminal.smc` | 200 alerts, 1000 scans/day |
| **xterminal** | `free` | ₹0/month | yes | *(none)* | 10 orders/day |
| | `pro` | ₹2,499/month | | `xterminal.algo`, `xterminal.basket` | 1000 orders/day |
| **intelligence** | `free` | ₹0/month | yes | `intelligence.search` | 50 queries/day |
| | `pro` | ₹1,999/month | | `intelligence.search`, `intelligence.llm`, `intelligence.export` | 2000 queries/day |

Entitlements and limits ride in the token as the `ent` and `lim` claims. A desk
reads them with `hasEntitlement("terminal.smc")` and `planLimit("alerts", 5)`.
Two consequences worth holding on to:

- **A plan edit is not instant.** It reaches a member on their next token, so
  allow up to 15 minutes before concluding an edit did not work.
- **Limits are advisory unless a desk enforces them.** Nothing here stops a
  request; the desk has to ask.

Exactly one plan per platform may be the default — saving a plan with *default*
ticked clears the flag on the others, because provisioning would otherwise pick
arbitrarily for a new member.

## Who currently holds what

| Platform | Role | Account | Plan | Subscription |
|---|---|---|---|---|
| intelligence | admin | `admin@hynt.one` | pro | active |
| intelligence | admin | `katla.jagadeesh@gmail.com` | pro | active |
| terminal | admin | `admin@hynt.one` | pro | active |
| terminal | admin | `katla.jagadeesh@gmail.com` | pro | active |
| xterminal | admin | `admin@hynt.one` | pro | active |
| xterminal | admin | `katla.jagadeesh@gmail.com` | pro | active |

Both accounts are admin + pro + active everywhere. **Nobody is on a free plan**,
so no limit in the table above is currently being exercised — worth knowing
before testing that limits behave.

## What the console shows, and to whom

| Tab | Visible when | Covers |
|---|---|---|
| **Platforms** | always | the launcher: your tiles, your role and plan on each |
| **Security** | always | profile name, password, 2FA, your signed-in devices |
| **Admin** | you hold an admin-rank role on ≥1 platform | one platform at a time: invite, add existing account, members, roles, plans |
| **Estate** | `is_superadmin` | accounts, platforms, OAuth clients, signing keys, audit |

Admin is scoped to the platforms you administer and to your rank on each — a
Terminal admin never sees X-Terminal. Estate is unscoped, which is why the two
destructive actions there (grant/revoke superadmin, rotate keys) confirm first.

### Admin

- **Invite someone new** — creates the account and shows a one-time temporary
  password. There is no mail on this box, so if it is not copied from the banner
  it is gone and must be reset.
- **Add an existing account** — grants an account that already exists elsewhere
  in the estate. Deliberately separate from invite: conflating them hands a
  second password to someone who already has one.
- **Members** — change role or plan inline, or remove from the platform.
  Removing a member does not delete their account.
- **Plans** — create and edit, including entitlements and limits.

### Estate

- **Accounts** — create, suspend, reinstate, reset password, grant/revoke
  superadmin. Suspension revokes tokens estate-wide within seconds.
- **Platforms** — name, base URL, description, icon. The slug is fixed once
  created: it is the token audience, so changing it would invalidate every token
  that names it.
- **Clients** — OAuth clients and their redirect URI allow-list, matched
  exactly. An unexplained `redirect_uri is not registered` at `/oauth/authorize`
  is this list.
- **Keys** — the signing keys, and rotation. A retired key stays published until
  the last token it signed expires, so rotating never signs anyone out.
- **Audit** — server-side filtering by action and row cap; the text and date
  boxes narrow what has already loaded, so widen the cap to search further back.
  CSV export covers the filtered rows.

## Not in the console yet

These have no endpoints behind them, so they are a backend change first:

- an admin view of **sessions and devices** for other users (`/auth/sessions`
  is self-only today)
- **API tokens / service accounts** for machine-to-machine access
- **security policy controls** — enforcing 2FA, session and token lifetimes,
  lockout thresholds — which live in `.env` today

## Changing any of this

Use the console. If you must go direct, the tables are `roles`, `plans`,
`memberships` and `subscriptions` in `hynt_accounts` — but a direct write skips
the audit log and the revocation publish, so a change made that way can take up
to 15 minutes to reach a desk with nothing recording who made it.
