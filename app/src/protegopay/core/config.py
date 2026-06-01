from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OIDC — provided by the concessionaire's IdP
    oidc_jwks_uri: str = "https://idp.example.com/.well-known/jwks.json"
    oidc_audience: str = "protegopay-pilot"
    oidc_issuer: str = "https://idp.example.com"

    # Session JWT (ProtegoPay's own short-lived session token)
    session_secret: str = "dev-secret-do-not-use-in-production"
    session_algorithm: str = "HS256"
    session_expiry_seconds: int = 900  # 15 minutes

    # HMAC key for pseudonymising external user sub claims
    external_id_hmac_key: str = "dev-hmac-key-do-not-use-in-production"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Database
    database_url: str = "sqlite:///./protegopay.db"

    # Rate limiting
    auth_fail_max: int = 5
    auth_fail_window_seconds: int = 900  # 15 minutes

    # App
    environment: str = "development"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
