"""Runtime configuration, read from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ledger:ledger@localhost:5432/ledger"
    # No default: the service must refuse to start with a guessable signing key.
    jwt_secret: str = Field(min_length=32)
    jwt_ttl_minutes: int = Field(default=12 * 60, gt=0)
    log_level: str = "INFO"
    cors_origins: list[str] = []
    # Argon2id cost. Defaults follow the OWASP minimum (19 MiB, t=2), which keeps
    # concurrent logins affordable on a 512 MB free-tier instance. Tests lower it.
    password_hash_time_cost: int = Field(default=2, ge=1)
    password_hash_memory_kib: int = Field(default=19_456, ge=8)
    # Directory holding the built frontend; served by the API when present.
    static_dir: str | None = None

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Hosts hand out ``postgres://`` URLs; SQLAlchemy needs the driver spelled out."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # populated from the environment
