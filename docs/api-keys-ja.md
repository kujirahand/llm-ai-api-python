# API キーの取得方法

English: [api-keys.md](api-keys.md)

クラウドのプロバイダーを使うには、各社の API キーが必要です。このページは、プロバイダーごとの発行手順と、このライブラリが読む環境変数の対応メモです。

共通の約束:

- キーは環境変数で渡します。コードやリポジトリにキーを書かないでください。
- キーは発行時に一度だけ表示されるものがほとんどです。パスワードマネージャーなど安全な場所に控えてください。
- API の利用料金は、各社の契約（ChatGPT や Claude のアプリ契約など）とは別に発生します。

```bash
export OPENAI_API_KEY="..."
```

## OpenAI

- 発行元: [OpenAI Platform の API keys](https://platform.openai.com/api-keys)
- 環境変数: `OPENAI_API_KEY`

1. OpenAI Platform にログインします。
2. API keys のページで「Create new secret key」を押し、キーをコピーして控えます（再表示はできません）。
3. Billing で支払い方法を登録し、必要ならクレジットを購入します。キーを作るだけでは課金されませんが、残高がないと API は呼べません。

## Anthropic（Claude）

- 発行元: [Anthropic Console](https://console.anthropic.com/) の Settings → API Keys
- 環境変数: `ANTHROPIC_API_KEY`

1. Anthropic Console にログインします。
2. Settings → API Keys で「Create Key」を押し、キーをコピーして控えます（再表示はできません）。
3. Billing でクレジットを購入します。購入した分だけ使えるプリペイド方式です。

## Google（Gemini）

- 発行元: [Google AI Studio の API key](https://aistudio.google.com/apikey)
- 環境変数: `GEMINI_API_KEY`（なければ `GOOGLE_API_KEY` も読まれます）

1. Google アカウントで Google AI Studio にログインします。
2. 「Create API key」を押し、キーをコピーして控えます。
3. AI Studio 経由のキーには無料枠があります。課金を有効にする場合は、紐づく Google Cloud プロジェクトで請求を有効にします。

## OpenRouter

- 発行元: [OpenRouter の Keys](https://openrouter.ai/keys)
- 環境変数: `OPENROUTER_API_KEY`

1. OpenRouter にログインします。
2. Keys のページで「Create Key」を押し、キーをコピーして控えます。
3. Credits でクレジットを購入します。購入した分だけ使えるプリペイド方式です。

## Grok（xAI）

- 発行元: [xAI Console](https://console.x.ai/) の API Keys
- 環境変数: `XAI_API_KEY`

1. xAI Console にログインします。
2. API Keys のページでキーを作成し、コピーして控えます。
3. クレジットを購入します。購入した分だけ使えるプリペイド方式で、残高がないと API は呼べません。

## Muse（Meta Model API）

- 発行元: [Meta for Developers](https://dev.meta.ai/)
- 環境変数: `MODEL_API_KEY`

1. dev.meta.ai にログインし、API キーを発行します。
2. 発行したキーを控えます。課金は従量制です。

## ローカルのプロバイダー（LM Studio / Ollama / Strata）

API キーは不要です。このライブラリには既定の仮キーが入っていて、そのまま接続できます。サーバー側で認証を有効にした場合だけ、環境変数（`LMSTUDIO_API_KEY`、`OLLAMA_API_KEY`、`STRATA_API_KEY`）でサーバー側のキーに合わせてください。詳しくは各サーバーのページを見てください。

- [LM Studio](local_llm-lmstudio-ja.md)
- [Ollama](local_llm-ollama-ja.md)
- [Strata](local_llm-strata-ja.md)
