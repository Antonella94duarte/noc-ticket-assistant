"""Token prices used to estimate what an analysis costs.

Prices in US$ per 1M tokens, from the providers' official pricing pages on 2026-10-24:

- OpenAI: https://developers.openai.com/api/docs/pricing
- DeepSeek: https://api-docs.deepseek.com/quick_start/pricing

Estimates are an upper bound: they use the uncached input price (cached input is 10x cheaper on
OpenAI and up to 50x on DeepSeek) and DeepSeek's peak-hour price (off-peak is half). Hidden
reasoning tokens are billed as output and are already part of the output count.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float


PRICES: dict[str, Price] = {
    "gpt-6-luna": Price(0.10, 0.50),
    "gpt-6-astra": Price(10.00, 50.00),
    "deepseek-flash": Price(0.30, 1.20),  # peak, cache miss
    "deepseek-v4-pro": Price(1.32, 3.96),  # peak, cache miss
}

FREE_PROVIDERS = {"ollama"}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    """US$ for one call or a sum of calls; None when the model's price is unknown."""
    if provider in FREE_PROVIDERS:
        return 0.0
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        input_tokens * price.input_per_million + output_tokens * price.output_per_million
    ) / 1_000_000
