from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values accepted by the OpenAI SDK; each model supports a subset (see its page in the docs).
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    """Application settings, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NOC Ticket Assistant"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://noc:noc@localhost:5432/noc_tickets"

    # Optional so the API starts without them; /tickets/analyze answers 503 until they are set.
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    # Reasoning tokens are billed as output. With "low", gpt-6-luna skipped reasoning and misjudged
    # severity on the sample tickets; "medium" got them right for ~50% more cost.
    openai_reasoning_effort: ReasoningEffort = "medium"


@lru_cache
def get_settings() -> Settings:
    return Settings()
