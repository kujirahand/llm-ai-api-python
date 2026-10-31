# Using prompt caching

`llm-ai-api` has no dedicated caching API. Request `content` and the response `raw` are passed through unchanged, so each provider's prompt caching works as is.

No extra argument is needed. Pass `content` written in the provider's own format to `chat()`.

## Claude (Anthropic)

Add `cache_control` to the block you want cached. The `content` of a `system` message can be a list of blocks; the library puts it into the top-level `system` field as is (see `test_system_blocks` in `tests/test_anthropic.py`).

```python
from llm_ai_api import llm, models

m = llm(models.ANTHROPIC_CLAUDE_SONNET_5_5)

long_text = open("manual.txt", encoding="utf-8").read()  # long shared context

messages = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": long_text,
                "cache_control": {"type": "ephemeral"},  # cache everything up to here
            }
        ],
    },
    {"role": "user", "content": "Summarize chapter 3."},
]

result = m.chat(messages)
print(result.text)
print(result.raw["usage"])
```

`ask()` and `stream()` take a plain string question, so use `chat()` when you pass a list of blocks.

From the second call on, the part that is identical to the previous call (the `system` above) is read from the cache. Check whether the cache was hit in `result.raw["usage"]`:

| Field | Meaning |
|---|---|
| `cache_creation_input_tokens` | Tokens written to the cache |
| `cache_read_input_tokens` | Tokens read from the cache |

`ChatResult.usage` (`input_tokens` / `output_tokens`) does not include these fields. Always read the cache status from `raw`.

The minimum cacheable size, lifetime and pricing differ by model. Check the official documentation for current values.

## OpenAI / OpenRouter / Google

OpenAI uses caching automatically for prompts above a certain length. Nothing is specified in the request. To make hits more likely, keep the leading part (`system` or shared material) identical between calls and put the part that changes at the end.

```python
m = llm(models.OPENAI_GPT6_LUNA)
result = m.chat([
    {"role": "system", "content": long_text},         # same every time
    {"role": "user", "content": "Summarize chapter 3."},  # changes every time
])
print(result.raw["usage"])  # look at prompt_tokens_details.cached_tokens, etc.
```

On OpenRouter and Google's OpenAI-compatible endpoint, caching behavior (automatic or needs `cache_control`, and the name of the usage field) differs by model. If needed, pass provider-specific parameters with `extra=` and check `result.raw["usage"]`. These combinations have not been verified against the real APIs.

## Notes

- Caching does not change the returned text. It changes latency and cost.
- A cache hit requires an identical prefix; a single differing character breaks it. Do not put timestamps or random values in the part you want cached.
- The format of `result.raw["usage"]` is defined by the provider and may change, so the library does not normalize it (see "pass-through first" in [AGENTS.md](../AGENTS.md)).
