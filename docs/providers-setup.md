# Setting up the model providers

The project runs on three providers. You only need the ones you want to use: the baseline API
needs OpenAI, and the agents use whatever `LLM_PROVIDER` points to.

| Provider | Needs an account | Cost | Data leaves your machine |
|---|---|---|---|
| OpenAI | Yes, with prepaid credit | Per token | Yes |
| DeepSeek | Yes, with prepaid credit | Per token, cheaper | Yes (servers in China) |
| Ollama | No | Free (runs on your GPU/CPU) | No |

All keys go in `.env` (copy it from `.env.example`). `.env` is git-ignored: never put a key in
`.env.example`, in the code or in a commit. If a key leaks, revoke it on the provider's site and
create a new one.

Pages and model names were checked on 2026-10-24; providers change them often, so check the
official pages linked below before budgeting.

## OpenAI

1. Sign in at https://platform.openai.com (a ChatGPT account works, but ChatGPT subscriptions do
   **not** include API usage).
2. Add prepaid credit in **Billing**:
   https://platform.openai.com/settings/organization/billing/overview. A few dollars cover this
   project many times over.
3. Optionally set a monthly spending cap in the **Limits** section of the organization settings.
4. Create a key at https://platform.openai.com/api-keys (**Create new secret key**). It is shown
   only once: copy it then.
5. In `.env`:

   ```
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-6-luna
   ```

- Models and what each supports: https://developers.openai.com/api/docs/models
- Prices: https://developers.openai.com/api/docs/pricing
- `gpt-6-luna` is the cheapest GPT-6 model and supports Structured Outputs and tool calling, which
  is all this project needs.

## DeepSeek

1. Sign in at https://platform.deepseek.com.
2. Add prepaid credit in **Top up**: without balance the API answers with an error.
3. Create a key in **API keys**. Like OpenAI, the full key is shown only once.
4. In `.env`:

   ```
   DEEPSEEK_API_KEY=sk-...
   DEEPSEEK_MODEL=deepseek-flash
   DEEPSEEK_REASONING_EFFORT=low
   ```

- Models and prices (cheaper off-peak; cached input costs almost nothing):
  https://api-docs.deepseek.com/quick_start/pricing
- Thinking mode, on by default: https://api-docs.deepseek.com/guides/thinking_mode
- Tool calls: https://api-docs.deepseek.com/guides/tool_calls
- The current models are `deepseek-flash` and `deepseek-v4-pro`. Some third-party docs (including
  LangChain's DeepSeek page) still show the retired `deepseek-chat` and `deepseek-reasoner`.

## Ollama (local, no key)

1. Install it from https://ollama.com/download.
2. Download a model that supports tool calling. On a laptop GPU with ~6 GB of memory:

   ```bash
   ollama pull qwen3:4b
   ```

   Model sizes and capabilities: https://ollama.com/library/qwen3
3. In `.env`:

   ```
   OLLAMA_MODEL=qwen3:4b
   # From inside Docker, the host's Ollama is http://host.docker.internal:11434
   OLLAMA_BASE_URL=http://localhost:11434
   ```

- Tool calling in Ollama: https://docs.ollama.com/capabilities/tool-calling
- Its default 4,096-token context is too small for the triage prompt; the project sets
  `OLLAMA_NUM_CTX=16384`. If the agent's report comes back empty, try `OLLAMA_REASONING=false`.

## Check that everything works

```bash
python scripts/check_providers.py            # every configured provider
python scripts/check_providers.py deepseek   # just one
```

For each provider it checks, with one real call each, that the model calls the right tool and
returns a valid structured classification, and prints latency and tokens. It costs a fraction of
a cent per provider.

## Privacy

Every example in this repository is synthetic. With real customer tickets, sending them to
OpenAI or DeepSeek means sending customer data to a third party: use the local model, or a
provider covered by a data processing agreement and approved by the customer.
