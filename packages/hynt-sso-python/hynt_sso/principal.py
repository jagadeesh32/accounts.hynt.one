"""The authenticated caller, as one platform sees them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Ranks mirror accounts.hynt.one. Kept here as data so a platform can ask
#: "admin or above" without enumerating every role above admin.
ROLE_RANK: dict[str, int] = {"superadmin": 40, "admin": 30, "staff": 20, "user": 10}


@dataclass(frozen=True, slots=True)
class Principal:
    """Everything the token said about this caller, on this platform.

    Frozen on purpose: a request handler that can edit its own principal is one
    refactor away from a privilege escalation that no test would catch.
    """

    user_id: str
    email: str
    name: str
    org_id: str
    platform: str
    role: str = "user"
    rank: int = 10
    permissions: tuple[str, ...] = ()
    plan: str | None = None
    plan_status: str | None = None
    entitlements: tuple[str, ...] = ()
    limits: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    token_version: int = 1
    email_verified: bool = False
    raw_claims: dict[str, Any] = field(default_factory=dict)

    # ----------------------------------------------------------------- roles
    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"

    @property
    def is_admin(self) -> bool:
        return self.has_role("admin")

    def has_role(self, minimum: str) -> bool:
        """True when this principal ranks at or above ``minimum``."""
        return self.rank >= ROLE_RANK.get(minimum, 999)

    # ----------------------------------------------------------- permissions
    def has_permission(self, code: str) -> bool:
        """Exact match, or a wildcard the role was granted.

        ``*`` is superadmin. ``terminal:*`` would grant everything under that
        prefix, so a platform can widen a role without listing every capability.
        """
        if "*" in self.permissions:
            return True
        if code in self.permissions:
            return True
        prefix = code.split(":", 1)[0]
        return f"{prefix}:*" in self.permissions

    def require_permission(self, code: str) -> None:
        if not self.has_permission(code):
            raise PermissionError(f"missing permission '{code}'")

    # ---------------------------------------------------------------- plans
    @property
    def plan_active(self) -> bool:
        return self.plan_status in ("active", "trialing")

    def has_entitlement(self, code: str) -> bool:
        """Is this feature unlocked by the subscribed plan?

        Separate from permissions on purpose: a role says what you are allowed to
        do, a plan says what you have paid for. An admin on the free tier is
        still on the free tier.
        """
        return self.plan_active and code in self.entitlements

    def limit(self, key: str, default: Any = None) -> Any:
        """A quota from the plan, e.g. ``principal.limit("scans_per_day", 25)``."""
        return self.limits.get(key, default)

    # --------------------------------------------------------------- output
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.user_id,
            "email": self.email,
            "name": self.name,
            "org_id": self.org_id,
            "platform": self.platform,
            "role": self.role,
            "rank": self.rank,
            "permissions": list(self.permissions),
            "plan": self.plan,
            "plan_status": self.plan_status,
            "entitlements": list(self.entitlements),
            "limits": self.limits,
            "email_verified": self.email_verified,
        }

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "Principal":
        return cls(
            user_id=str(claims.get("sub", "")),
            email=claims.get("email", ""),
            name=claims.get("name", ""),
            org_id=str(claims.get("org", "")),
            platform=claims.get("aud", ""),
            role=claims.get("role", "user"),
            rank=int(claims.get("rank", 10) or 10),
            permissions=tuple(claims.get("perms") or ()),
            plan=claims.get("plan"),
            plan_status=claims.get("plan_status"),
            entitlements=tuple(claims.get("ent") or ()),
            limits=dict(claims.get("lim") or {}),
            session_id=claims.get("sid"),
            token_version=int(claims.get("tv", 1) or 1),
            email_verified=bool(claims.get("email_verified")),
            raw_claims=claims,
        )
