"""FastAPI dependencies.

All three platforms are FastAPI, so this is the layer that lets their existing
route signatures keep working while the credential behind them changes.
"""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, Query, WebSocket, status

from hynt_sso.client import HyntSSO, TokenError
from hynt_sso.principal import Principal

_UNAUTHENTICATED = {"WWW-Authenticate": "Bearer"}


def build_dependencies(sso: HyntSSO, *, dev_principal: Principal | None = None):
    """Return ``(current_user, require_role, require_permission)``.

    ``dev_principal`` short-circuits verification when a platform is running with
    auth disabled locally. It is a parameter rather than an environment lookup so
    that shipping it to production requires an actual code change.
    """

    def _extract(authorization: str | None, token: str | None) -> str | None:
        # The header is the real path; the query parameter exists for EventSource
        # and WebSocket clients, which cannot set headers.
        return HyntSSO.bearer_from_header(authorization) or token

    async def current_user(
        authorization: Annotated[str | None, Header()] = None,
        token: Annotated[str | None, Query()] = None,
    ) -> Principal:
        if dev_principal is not None:
            return dev_principal

        raw = _extract(authorization, token)
        if not raw:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Not authenticated.", _UNAUTHENTICATED
            )
        try:
            return sso.principal(raw)
        except TokenError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, str(exc), _UNAUTHENTICATED
            ) from exc

    def require_role(minimum: str) -> Callable:
        """``Depends(require_role("admin"))`` — admin or above."""

        async def dependency(user: Annotated[Principal, Depends(current_user)]) -> Principal:
            if not user.has_role(minimum):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"This action requires the {minimum} role or above.",
                )
            return user

        return dependency

    def require_permission(code: str) -> Callable:
        """``Depends(require_permission("terminal:broker.manage"))``.

        Preferred over require_role: it says what the route needs, so tightening
        a role does not mean auditing every role comparison in the codebase.
        """

        async def dependency(user: Annotated[Principal, Depends(current_user)]) -> Principal:
            if not user.has_permission(code):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, f"Missing permission '{code}'."
                )
            return user

        return dependency

    def require_entitlement(code: str) -> Callable:
        """Gate a paid feature on the subscribed plan.

        Answers 402 rather than 403 — the caller is allowed to do this, they have
        simply not paid for it, and the UI should offer an upgrade rather than an
        error.
        """

        async def dependency(user: Annotated[Principal, Depends(current_user)]) -> Principal:
            if not user.has_entitlement(code):
                raise HTTPException(
                    status.HTTP_402_PAYMENT_REQUIRED,
                    f"Your plan does not include '{code}'.",
                )
            return user

        return dependency

    current_user.require_role = require_role
    current_user.require_permission = require_permission
    current_user.require_entitlement = require_entitlement
    return current_user, require_role, require_permission


def websocket_principal(sso: HyntSSO, websocket: WebSocket) -> Principal | None:
    """Authenticate a WebSocket upgrade from its ``?token=`` query parameter."""
    return sso.principal_or_none(websocket.query_params.get("token"))
