from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values accepted by the OpenAI SDK; each model supports a subset (see its page in the docs).
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

Provider = Literal["openai", "deepseek", "ollama"]
PROVIDERS: tuple[Provider, ...] = ("openai", "deepseek", "ollama")


class Settings(BaseSettings):
    """Application settings, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NOC Ticket Assistant"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://noc:noc@localhost:5433/noc_tickets"

    # Optional so the API starts without them; /tickets/analyze answers 503 until they are set.
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    # Reasoning tokens are billed as output. With "low", gpt-6-luna skipped reasoning and misjudged
    # severity on the sample tickets; "medium" got them right for ~50% more cost.
    openai_reasoning_effort: ReasoningEffort = "medium"
    # Per request; the SDK retries twice, and each analysis makes two chained calls.
    openai_timeout_seconds: float = 60.0

    # --- Agents (app/llm/providers.py): any provider, chosen here ---
    llm_provider: Provider = "openai"
    # Comma-separated, tried in order when the primary provider fails: "deepseek,ollama".
    llm_fallback_providers: str = ""
    # Applied to providers that accept it (not to OpenAI reasoning models).
    llm_temperature: float = 0.0
    # Cost cap per model call; reasoning models count their hidden reasoning against it.
    llm_max_tokens: int = 4000

    deepseek_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    # DeepSeek thinks by default (None keeps that). Thinking mode ignores temperature and can't
    # force a tool call, so structured output then uses JSON mode (see app/llm/providers.py).
    deepseek_thinking: bool | None = None
    # Thinking effort ("high" is DeepSeek's own default). At "high" the long report prompt spent
    # the whole LLM_MAX_TOKENS budget on reasoning and returned no answer, so we default to low.
    deepseek_reasoning_effort: Literal["low", "high", "max"] | None = "low"

    # From inside Docker the host's Ollama is http://host.docker.internal:11434.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    # Thinking models such as qwen3 reason before answering by default (None keeps the model's
    # default). False is much faster on a laptop GPU, at some cost in accuracy.
    ollama_reasoning: bool | None = None
    # Context window. Ollama's default (4096 tokens) is too small for the few-shot triage prompt
    # plus a JSON schema: the model then answers with nothing. More context uses more VRAM.
    ollama_num_ctx: int = 16384

    # Investigation agent: after this many tool calls it must conclude with what it found; the
    # model-call limit is the hard stop that keeps a confused agent from looping on our bill.
    agent_max_tool_calls: int = 8
    agent_max_model_calls: int = 6

    @property
    def fallback_providers(self) -> list[Provider]:
        names = [name.strip().lower() for name in self.llm_fallback_providers.split(",")]
        unknown = [name for name in names if name and name not in PROVIDERS]
        if unknown:
            raise ValueError(f"Unknown LLM fallback provider(s): {', '.join(unknown)}")
        # Keep the order, drop duplicates and the primary itself.
        ordered = dict.fromkeys(name for name in names if name and name != self.llm_provider)
        return list(ordered)


@lru_cache
def get_settings() -> Settings:
    return Settings()
