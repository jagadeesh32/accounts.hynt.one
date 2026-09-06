# hynt-sso (Python)

Verifies `accounts.hynt.one` access tokens inside a platform backend, locally,
against a cached JWKS.

```python
from hynt_sso import HyntSSO, TokenError

sso = HyntSSO(issuer="https://accounts.hynt.one", audience="terminal")

principal = sso.bearer(request.headers.get("authorization"))
principal.has_role("staff")                  # rank >= staff
principal.has_permission("terminal:scanner.run")
principal.has_entitlement("terminal.intraday")
principal.limit("scans_per_day", 25)
```

Install from the estate checkout:

```bash
pip install -e /opt/accounts.hynt.one/packages/hynt-sso-python
```

`check_revocations=True` (the default) polls `/api/v1/revocations` about every
30 seconds so a suspended account stops working in seconds rather than at token
expiry. The poll **fails open**: if the identity provider is unreachable the
cache is kept and retried, because refusing every request across the estate is a
worse failure than honouring a revoked token for the rest of its 15 minutes.
