"""Hynt SSO client — verify accounts.hynt.one tokens inside a platform backend.

Drop-in replacement for the per-platform auth modules. Verification is local:
the JWKS is fetched once and cached, so authorising a request costs a signature
check, not a network round-trip to the identity provider.

    from hynt_sso import HyntSSO
    from hynt_sso.fastapi import build_dependencies

    sso = HyntSSO(issuer="https://accounts.hynt.one", audience="terminal")
    current_user, require_role, require_permission = build_dependencies(sso)
"""

from hynt_sso.client import HyntSSO, TokenError
from hynt_sso.principal import Principal

__all__ = ["HyntSSO", "Principal", "TokenError"]
__version__ = "1.0.0"
