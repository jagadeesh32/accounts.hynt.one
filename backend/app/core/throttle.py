"""In-process rate limiting for the credential endpoints.

Deliberately in-memory: the unit runs --workers 1, and a login limiter that
needs Redis to be up is a limiter that fails open on the day Redis is down.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)


def check(key: str, *, limit: int | None = None, window: int | None = None) -> None:
    limit = limit or settings.login_max_attempts
    window = window or settings.login_window_seconds
    now = time.monotonic()

    bucket = _hits[key]
    while bucket and bucket[0] <= now - window:
        bucket.popleft()

    if len(bucket) >= limit:
        retry_after = int(window - (now - bucket[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)


def reset(key: str) -> None:
    """Called on a successful login so one fat-fingered evening does not lock
    someone out for the rest of the window."""
    _hits.pop(key, None)
