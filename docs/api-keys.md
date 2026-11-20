# Getting an API key

日本語: [api-keys-ja.md](api-keys-ja.md)

To use a cloud provider you need that provider's API key. This page is a memo of where each key is issued and which environment variable this library reads for it.

Common rules:

- Pass keys through environment variables. Never write a key into your code or repository.
- Most keys are shown only once, when they are created. Keep yours in a password manager or another safe place.
- API usage is billed separately from any app subscription you may have (such as ChatGPT or the Claude app).

```bash
export OPENAI_API_KEY="..."
```

## OpenAI

- Issued at: [API keys on OpenAI Platform](https://platform.openai.com/api-keys)
- Environment variable: `OPENAI_API_KEY`

1. Sign in to OpenAI Platform.
2. On the API keys page, choose "Create new secret key" and copy the key (it cannot be shown again).
3. Under Billing, add a payment method and, if needed, buy credits. Creating a key is free, but calls fail without a balance or payment method.

## Anthropic (Claude)

- Issued at: [Anthropic Console](https://console.anthropic.com/), under Settings → API Keys
- Environment variable: `ANTHROPIC_API_KEY`

1. Sign in to the Anthropic Console.
2. Under Settings → API Keys, choose "Create Key" and copy the key (it cannot be shown again).
3. Under Billing, buy credits. Usage is prepaid: you can spend up to the credits you bought.

## Google (Gemini)

- Issued at: [API key in Google AI Studio](https://aistudio.google.com/apikey)
- Environment variable: `GEMINI_API_KEY` (`GOOGLE_API_KEY` is also read if the first is unset)

1. Sign in to Google AI Studio with your Google account.
2. Choose "Create API key" and copy the key.
3. Keys from AI Studio include a free tier. To enable billing, turn on billing for the linked Google Cloud project.

## OpenRouter

- Issued at: [Keys on OpenRouter](https://openrouter.ai/keys)
- Environment variable: `OPENROUTER_API_KEY`

1. Sign in to OpenRouter.
2. On the Keys page, choose "Create Key" and copy the key.
3. Under Credits, buy credits. Usage is prepaid: you can spend up to the credits you bought.

## Grok (xAI)

- Issued at: [xAI Console](https://console.x.ai/), under API Keys
- Environment variable: `XAI_API_KEY`

1. Sign in to the xAI Console.
2. On the API Keys page, create a key and copy it.
3. Buy credits. Usage is prepaid, and calls fail without a balance.

## Muse (Meta Model API)

- Issued at: [Meta for Developers](https://dev.meta.ai/)
- Environment variable: `MODEL_API_KEY`

1. Sign in to dev.meta.ai and create an API key.
2. Keep the key somewhere safe. Usage is billed pay-as-you-go.

## Local providers (LM Studio / Ollama / Strata)

No API key is needed. This library sends a built-in placeholder key, so connections work as they are. Only when you have enabled authentication on the server side, match it with the environment variable (`LMSTUDIO_API_KEY`, `OLLAMA_API_KEY`, `STRATA_API_KEY`). See each server's page for details.

- [LM Studio](local_llm-lmstudio.md)
- [Ollama](local_llm-ollama.md)
- [Strata](local_llm-strata.md)
