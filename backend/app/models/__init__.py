"""All ORM models.

Imported as one module so that ``Base.metadata`` is complete before Alembic
autogenerate or ``create_all`` runs. A model that is only imported by the route
that uses it is a model Alembic will happily propose dropping.
"""

from app.models.billing import (
    BillingInterval,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.models.identity import (
    LoginAttempt,
    Organization,
    PasswordReset,
    SsoSession,
    User,
    UserStatus,
)
from app.models.oauth import (
    AuditLog,
    AuthorizationCode,
    OAuthClient,
    RefreshToken,
    Revocation,
    SigningKey,
)
from app.models.rbac import (
    ROLE_RANK,
    Membership,
    Permission,
    Platform,
    Role,
    RoleCode,
    RolePermission,
)

__all__ = [
    "AuditLog", "AuthorizationCode", "BillingInterval", "LoginAttempt", "Membership",
    "OAuthClient", "Organization", "PasswordReset", "Permission", "Plan", "Platform",
    "RefreshToken", "Revocation", "ROLE_RANK", "Role", "RoleCode", "RolePermission", "SigningKey",
    "SsoSession", "Subscription", "SubscriptionStatus", "User", "UserStatus",
]
