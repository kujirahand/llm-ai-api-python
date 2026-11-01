# Structured output

`LLM.chat()` and `LLM.achat()` accept `schema=` to request JSON structured output. The validated value lands in `ChatResult.parsed`. Streaming (`ask_stream()` / `chat_stream()` and friends) does not support it.

## Usage

Passing a JSON Schema dict:

```python
from llm_ai_api import llm

result = llm("openai:gpt-6-luna").chat(
    [{"role": "user", "content": "Give me one name for a dog"}],
    schema={
        "title": "DogName",
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
print(result.parsed["name"])  # the value read as a dict
```

A pydantic-v2-compatible model class (anything with `model_json_schema()` and `model_validate_json()`) works too. This library does not depend on pydantic, so the model class is yours to define.

```python
from pydantic import BaseModel


class DogName(BaseModel):
    name: str


result = m.chat(messages, schema=DogName)
dog: DogName = result.parsed  # the validated object
```

## Provider formats

| Provider | What is sent |
|---|---|
| OpenAI / OpenRouter / Google | `response_format` (`json_schema`, strict) |
| Anthropic | `output_config.format` (`json_schema`) |

For the OpenAI family, the schema name comes from the schema's `title`, then the model class's `__name__`, then `"response"`.

## Schema normalization

Schemas taken from a model class are copied and normalized so they pass strict mode (the original schema is not modified):

- object nodes get `additionalProperties: false`
- `required` becomes all properties
- properties that were optional become nullable
- property `default` values are removed

A JSON Schema passed as a dict is sent unchanged.

## Errors

| Situation | Exception |
|---|---|
| The model refused | `StructuredOutputError` (`code="output_refused"`) |
| The output did not finish (length limit and the like) | `StructuredOutputError` (`code="output_incomplete"`) |
| Not readable as JSON / model validation failed | `StructuredOutputError` (`code="invalid_structured_output"`, the original exception is `__cause__`) |
| An invalid `schema=` value | `LLMConfigError` (`code="invalid_schema"`) |

`StructuredOutputError.result` holds the original `ChatResult`, so the (already paid for) response — `text`, `raw` — is not lost.

## Overriding with extra

As always, `extra` is applied last and wins over the generated keys. For the OpenAI family, `extra={"response_format": ...}` replaces the generated setting entirely. Anthropic's `output_config` is merged shallowly, so adding another key with `extra={"output_config": {"effort": "high"}}` keeps the generated `format`.
