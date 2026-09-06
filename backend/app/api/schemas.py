"""Request/response shapes. Kept in one file — they are small and shared."""
from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    otp: str | None = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)


class TokenIn(BaseModel):
    """POST /oauth/token — form-encoded in the spec, JSON here as well because
    the browser SDK sends JSON and both are trivially supported."""
    grant_type: str = "authorization_code"
    code: str
    client_id: str
    redirect_uri: str
    code_verifier: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str | None
    status: str
    is_superadmin: bool
    mfa_enabled: bool
    created_at: str | None = None
    last_login_at: str | None = None


class CreateUserIn(BaseModel):
    email: EmailStr
    full_name: str | None = None
    password: str | None = None
    platform: str | None = None
    role: str = "user"
    plan: str | None = None


class GrantIn(BaseModel):
    email: EmailStr
    platform: str
    role: str
    plan: str | None = None


class PlanIn(BaseModel):
    slug: str
    name: str
    price_inr: int = 0
    interval: str = "month"
    entitlements: list[str] = []
    limits: dict = {}
    is_default: bool = False


class SubscriptionIn(BaseModel):
    email: EmailStr
    platform: str
    plan: str
    status: str = "active"


class PlatformIn(BaseModel):
    slug: str
    name: str
    base_url: str = ""
    description: str = ""
    icon: str = ""


class ClientIn(BaseModel):
    client_id: str
    name: str
    platform: str
    redirect_uris: list[str]
    is_public: bool = True
