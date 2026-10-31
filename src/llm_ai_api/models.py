"""代表的なモデルの定数。`llm()` にそのまま渡せる `"プロバイダー:モデル"` 形式の文字列。

    from llm_ai_api import llm, models
    m = llm(models.OPENAI_GPT6_LUNA)

ここにあるのは例であり、モデルは頻繁に入れ替わる。載っていないモデルや、より新しいモデルは
`llm("openai:任意のモデル名")` のように文字列でそのまま指定できる。この定数を経由する必要はない。

命名規則: `<プロバイダー>_<モデル名>`（OpenRouter は `OPENROUTER_<ベンダー>_<モデル名>`）。
モデル名は大文字にして `-` と `.` を `_` に置き換える。
"""

# --- OpenAI（api.openai.com 直接） -------------------------------------------
OPENAI_GPT6_ASTRA = "openai:gpt-6-astra"
OPENAI_GPT6_LUNA = "openai:gpt-6-luna"
OPENAI_GPT6_SOL = "openai:gpt-6-sol"
OPENAI_GPT6_SOL_PRO = "openai:gpt-6-sol-pro"
OPENAI_GPT6_1_SOL = "openai:gpt-6.1-sol"
OPENAI_GPT6_1_TERRA = "openai:gpt-6.1-terra"

# --- Anthropic (Claude) -------------------------------------------------------
ANTHROPIC_CLAUDE_FABLE_5_1 = "anthropic:claude-fable-5-1"
ANTHROPIC_CLAUDE_OPUS_5_5 = "anthropic:claude-opus-5-5"
ANTHROPIC_CLAUDE_SONNET_5_5 = "anthropic:claude-sonnet-5-5"
ANTHROPIC_CLAUDE_HAIKU_5_5 = "anthropic:claude-haiku-5-5"

# --- Google Gemini (generativelanguage.googleapis.com) ------------------------
GOOGLE_GEMINI_4_ARGON = "google:gemini-4-argon"
GOOGLE_GEMINI_3_8_FLASH = "google:gemini-3.8-flash"
GOOGLE_GEMINI_3_5_FLASH_LITE = "google:gemini-3.5-flash-lite"
GOOGLE_GEMINI_3_1_PRO_PREVIEW = "google:gemini-3.1-pro-preview"

# --- OpenRouter（モデル名は `ベンダー/モデル`。バージョンの区切りは `.`） ------------
OPENROUTER_OPENAI_GPT6_LUNA = "openrouter:openai/gpt-6-luna"
OPENROUTER_OPENAI_GPT6_SOL = "openrouter:openai/gpt-6-sol"
OPENROUTER_ANTHROPIC_CLAUDE_FABLE_5_1 = "openrouter:anthropic/claude-fable-5.1"
OPENROUTER_ANTHROPIC_CLAUDE_OPUS_5_5 = "openrouter:anthropic/claude-opus-5.5"
OPENROUTER_ANTHROPIC_CLAUDE_SONNET_5_5 = "openrouter:anthropic/claude-sonnet-5.5"
OPENROUTER_ANTHROPIC_CLAUDE_HAIKU_5_5 = "openrouter:anthropic/claude-haiku-5.5"
OPENROUTER_GOOGLE_GEMINI_3_8_FLASH = "openrouter:google/gemini-3.8-flash"
OPENROUTER_DEEPSEEK_DEEPSEEK_V4_PRO = "openrouter:deepseek/deepseek-v4-pro"
OPENROUTER_META_LLAMA_LLAMA_4_MAVERICK = "openrouter:meta-llama/llama-4-maverick"
