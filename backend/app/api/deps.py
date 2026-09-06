"""Shared dependency shorthands."""
from app.core.authz import Actor, current_actor, require_superadmin

__all__ = ["Actor", "current_actor", "require_superadmin"]
