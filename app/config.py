from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NOC Ticket Assistant"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://noc:noc@localhost:5432/noc_tickets"

    # LLM settings are optional until phase 1, when the analyzer starts using them.
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
