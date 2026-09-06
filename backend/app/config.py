"""Settings. Everything is env-driven so the systemd unit is the only place
production values live (EnvironmentFile=/opt/accounts.hynt.one/backend/.env)."""
from functools import lru_cache

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
