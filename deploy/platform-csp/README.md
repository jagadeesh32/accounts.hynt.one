# Platform nginx configs — the two CSP directives SSO needs

Copies of the three platform vhosts, kept here because their live configs live
only in `/etc/nginx/sites-available/` and are not tracked in their own repos.
They are **reference copies, not the source of truth** — edit `/etc/nginx/` and
re-copy, or the next `nginx -t` will be testing something else.

Each of the three needs exactly two additions to its CSP, or SSO half-works in a
way that is hard to read from the symptom:

```nginx
set $csp "${csp}; frame-src https://accounts.hynt.one";
set $csp "${csp}; connect-src 'self' https://accounts.hynt.one";
```

**`frame-src`** — silent renewal loads `accounts.hynt.one/oauth/authorize?prompt=none`
in a hidden iframe. `frame-src` has no default of its own, so the browser falls
back to `default-src 'self'` and blocks it:

> Framing 'https://accounts.hynt.one/' violates the following Content Security
> Policy directive: "default-src 'self'".

The user still gets in — the first sign-in is a redirect, not a frame — so this
looks fine until the fifteen-minute token expires and every session bounces back
to the sign-in page.

**`connect-src`** — the callback page POSTs the authorization code to
`accounts.hynt.one/oauth/token`, which is cross-origin from the platform. Without
this, sign-in fails at the last step, after the redirect has already succeeded.

The matching half is on accounts.hynt.one: `frame-ancestors 'self'
https://*.hynt.one`, and **no `X-Frame-Options` header at all** — that header
cannot express "these other origins may frame me", so sending `SAMEORIGIN`
alongside `frame-ancestors` only misleads whoever reads it next.
