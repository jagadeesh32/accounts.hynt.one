"""Settings. Everything is env-driven so the systemd unit is the only place
production values live (EnvironmentFile=/opt/accounts.hynt.one/backend/.env)."""
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HYNT_", env_file=".env", extra="ignore"
    )

    # --- identity ---
    issuer: str = "https://accounts.hynt.one"
    environment: str = "production"

    # --- database ---
    database_url: str = "postgresql+asyncpg://hynt_accounts@127.0.0.1/hynt_accounts"

    # --- the SSO cookie ---
    # The estate shares one cookie across *.hynt.one; on localhost there is no
    # parent domain to share, so dev leaves cookie_domain empty and relies on
    # the Vite proxy to keep everything same-origin.
    cookie_name: str = "hynt_sso"
    cookie_domain: str = ".hynt.one"
    cookie_secure: bool = True
    # SameSite for the SSO cookie. Empty = derive it from cookie_secure, which
    # is what both environments actually want:
    #
    #   production  (secure=True)  -> "none"
    #   local dev   (secure=False) -> "lax"
    #
    # "none" is not a relaxation here, it is the requirement. Silent renewal
    # loads /oauth/authorize?prompt=none in a hidden iframe on the *platform's*
    # origin (intelligence.hynt.one, ...), which is cross-site to this one. Lax
    # cookies are sent only on top-level navigations, so the iframe arrives with
    # no cookie, resolve_session() returns None, and the renewal is answered
    # "login_required" — every time. The symptom is a platform that signs in
    # once by full redirect and then 401s on /api/auth/me forever.
    #
    # CSRF is not what Lax was buying us: this cookie is an opaque session id
    # that is only ever read by GET /oauth/authorize, which mints nothing until
    # a registered redirect_uri and a PKCE challenge both check out.
    #
    # Browsers reject SameSite=None without Secure, so the derived value never
    # produces that combination; an explicit override must respect it too.
    cookie_samesite: str = ""
    session_ttl_days: int = 30
    session_idle_days: int = 7

    # --- tokens ---
    access_token_ttl_seconds: int = 900          # 15 minutes, per README
    auth_code_ttl_seconds: int = 60              # 60 seconds, per README
    key_dir: str = "var/keys"

    # --- throttle ---
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    # --- ops ---
    # Comma separated, and required in production: the platform SPAs exchange
    # their auth code against /oauth/token with a cross-origin fetch.
    cors_origins: str = ""
    trusted_redirect_hosts: str = "hynt.one"     # suffix allow-list for redirect_uri

    @model_validator(mode="after")
    def _check_cookie_samesite(self) -> "Settings":
        """Resolve and validate at construction, so a bad combination is a boot
        failure. As a lazily-evaluated property this raised inside the request
        that set the cookie, which surfaced as a 500 on sign-in — a config
        mistake wearing the costume of an application bug."""
        value = (self.cookie_samesite or ("none" if self.cookie_secure else "lax")).lower()
        if value not in ("lax", "strict", "none"):
            raise ValueError(f"HYNT_COOKIE_SAMESITE must be lax, strict or none (got {value!r})")
        if value == "none" and not self.cookie_secure:
            raise ValueError("HYNT_COOKIE_SAMESITE=none requires HYNT_COOKIE_SECURE=true")
        self.cookie_samesite = value
        return self

    @property
    def samesite(self) -> Literal["lax", "strict", "none"]:
        return self.cookie_samesite  # type: ignore[return-value]

    @property
    def redirect_host_suffixes(self) -> list[str]:
        return [h.strip() for h in self.trusted_redirect_hosts.split(",") if h.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
