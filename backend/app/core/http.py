"""Request/response helpers for Cello handlers.

Cello has no dependency injection, so the plumbing every handler needs — a
database session, the authenticated user, a uniform error shape — is expressed
as decorators here rather than repeated in each route.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from cello import Response

from app import config
from app.db import session_scope

log = logging.getLogger("hynt.http")


class ApiError(Exception):
    """Raised anywhere in a handler; rendered as a JSON error by @endpoint."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def to_response(self) -> Response:
        payload = {"error": self.code, "message": self.message, **self.extra}
        return Response.json(payload, status=self.status)


def bad_request(message: str, code: str = "invalid_request", **extra: Any) -> ApiError:
    return ApiError(400, code, message, **extra)


def unauthorized(message: str = "Not authenticated.", code: str = "unauthorized") -> ApiError:
    return ApiError(401, code, message)


def forbidden(message: str = "Insufficient permissions.", code: str = "forbidden") -> ApiError:
    return ApiError(403, code, message)


def not_found(message: str = "Not found.", code: str = "not_found") -> ApiError:
    return ApiError(404, code, message)


def conflict(message: str, code: str = "conflict") -> ApiError:
    return ApiError(409, code, message)


def too_many(message: str, retry_after: int) -> ApiError:
    return ApiError(429, "too_many_requests", message, retry_after=retry_after)


# --------------------------------------------------------------------------- #
#  Request reading
# --------------------------------------------------------------------------- #
def body_json(request) -> dict:
    """Parsed JSON body, or {} when absent. A malformed body is a 400, not a 500."""
    try:
        data = request.json()
    except Exception:
        raise bad_request("Request body must be valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def field(data: dict, name: str, *, required: bool = True, default: Any = None) -> Any:
    value = data.get(name, default)
    if required and (value is None or (isinstance(value, str) and not value.strip())):
        raise bad_request(f"'{name}' is required.", code="missing_field", field=name)
    return value


def query(request, name: str, default: str | None = None) -> str | None:
    value = request.get_query_param(name)
    return default if value in (None, "") else value


def client_ip(request) -> str | None:
    """Honours the first hop of X-Forwarded-For, which is what nginx sets."""
    try:
        # client_ip/user_agent are methods on Cello's Request, not properties.
        ip = request.client_ip()
    except Exception:
        return None
    if not ip:
        return None
    return ip.split(",")[0].strip() or None


def user_agent(request) -> str | None:
    try:
        return request.user_agent() or None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Cookies
# --------------------------------------------------------------------------- #
def get_cookie(request, name: str) -> str | None:
    """Cello's Request exposes no cookie jar, so parse the header.

    Split on ';' only — a cookie *value* may legitimately contain '=' (base64
    padding), so the name is everything before the first '=' and the value is
    all of the rest.
    """
    header = request.get_header("cookie") or request.get_header("Cookie")
    if not header:
        return None
    for part in header.split(";"):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        if sep and key.strip() == name:
            return value.strip()
    return None


def build_cookie(name: str, value: str, *, max_age: int, delete: bool = False) -> str:
    attrs = [f"{name}={value}", "Path=/", "HttpOnly", f"SameSite={config.COOKIE_SAMESITE}"]
    if config.COOKIE_DOMAIN:
        attrs.insert(1, f"Domain={config.COOKIE_DOMAIN}")
    if config.COOKIE_SECURE:
        attrs.append("Secure")
    attrs.append("Max-Age=0" if delete else f"Max-Age={max_age}")
    if delete:
        attrs.append("Expires=Thu, 01 Jan 1970 00:00:00 GMT")
    return "; ".join(attrs)


def with_cookie(response: Response, cookie: str) -> Response:
    """Attach the SSO cookie.

    Cello stores response headers in a HashMap, so a response carries exactly one
    Set-Cookie. The whole session design fits in one cookie for that reason —
    see the note in app.config.
    """
    response.set_header("Set-Cookie", cookie)
    return response


# --------------------------------------------------------------------------- #
#  Serialisation
# --------------------------------------------------------------------------- #
def jsonable(value: Any) -> Any:
    """Make ORM-adjacent values safe for Cello's Rust JSON serialiser."""
    import enum
    import uuid as _uuid

    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        # Naive datetimes from the driver are UTC by construction here; stamping
        # the zone explicitly stops the frontend guessing local time.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def ok(payload: Any, status: int = 200) -> Response:
    return Response.json(jsonable(payload), status=status)


def redirect(location: str, *, cookie: str | None = None) -> Response:
    response = Response.redirect(location)
    if cookie:
        response.set_header("Set-Cookie", cookie)
    return response


# --------------------------------------------------------------------------- #
#  Handler decorators
# --------------------------------------------------------------------------- #
def endpoint(func: Callable) -> Callable:
    """Give a handler a database session and a uniform error contract.

    The wrapped function is called as ``func(request, db)``. The session commits
    when the handler returns and rolls back if it raises, so no handler ever
    leaves a half-applied change behind.
    """

    @wraps(func)
    def wrapper(request):
        try:
            with session_scope() as db:
                result = func(request, db)
            return result if isinstance(result, Response) else ok(result)
        except ApiError as exc:
            return exc.to_response()
        except Exception:
            log.exception("unhandled error in %s", func.__name__)
            if config.DEBUG:
                import traceback
                return Response.json(
                    {"error": "server_error", "message": traceback.format_exc()}, status=500
                )
            return Response.json(
                {"error": "server_error", "message": "Something went wrong."}, status=500
            )

    return wrapper
