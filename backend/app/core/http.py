"""Small request-layer helpers."""
import uuid

from fastapi import HTTPException, status


def parse_uuid(value: str, what: str = "id") -> uuid.UUID:
    """Path params arrive as strings; asyncpg wants a real UUID and raises a
    500-shaped DataError on anything else. A bad id is a 404, not a crash."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such {what}")
