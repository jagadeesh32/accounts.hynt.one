# Platform nginx configs — the two CSP directives SSO needs

Copies of the three platform vhosts, kept here because their live configs live
only in `/etc/nginx/sites-available/` and are not tracked in their own repos.
They are **reference copies, not the source of truth** — edit `/etc/nginx/` and
re-copy, or the next `nginx -t` will be testing something else.

Each of the three needs these, or SSO half-works in a way that is hard to read
from the symptom:

```nginx
set $csp "${csp}; frame-src 'self' https://accounts.hynt.one";
set $csp "${csp}; frame-ancestors 'self'";
set $csp "${csp}; connect-src 'self' https://accounts.hynt.one";
add_header X-Frame-Options "SAMEORIGIN" always;
```

**Both origins in `frame-src`, and `frame-ancestors 'self'`.** This is the pair
that gets missed, because listing only accounts *looks* complete. Silent renewal
is a two-hop journey inside the hidden iframe: it opens
`accounts.hynt.one/oauth/authorize?prompt=none`, and accounts does not render a
result — it **302s the iframe back to this origin's `/auth/callback`**, which is
where `relaySilentCallback()` posts the code up to the parent.

So the frame lands on this origin, and two directives have to agree about that:

* `frame-src` governs every navigation in the frame, redirects included. Without
  `'self'` the final hop is blocked.
* `frame-ancestors 'none'` refuses framing by *every* ancestor, the same origin
  included, so the callback would refuse to render even once `frame-src` allows
  it. `'self'` still blocks the cross-origin framing the directive is for.
* `X-Frame-Options: DENY` does the same thing to browsers too old to understand
  `frame-ancestors`. `SAMEORIGIN` matches.

Get any of them wrong and the failure looks nothing like a CSP problem: the
frame loads nothing, posts nothing, and the parent sits on its 10-second
timeout — twice, because boot fetches config and me — so the app hangs on
"starting…" for 20-30 seconds and then shows the sign-in gate. Server-side
checks all pass, because none of this exists outside a browser.

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
