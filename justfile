# Run the unit test suite.
test:
    PYTHONPATH=src python -m unittest discover -s tests -t .

# Run only the OpenAI live tests with the low-cost GPT-6 Luna model.
# Responses are cached between runs; the JSONL log records cache hits as well.
test-openai:
    @if [ -z "${OPENAI_API_KEY:-}" ]; then echo "OPENAI_API_KEY is required"; exit 1; fi
    @LLM_AI_API_LIVE=1 LIVE_OPENAI_MODEL=gpt-6-luna LLM_AI_API_CACHE_DIR=.cache/llm-ai-api/test-openai/cache LLM_AI_API_LOG_DIR=.cache/llm-ai-api/test-openai/log PYTHONPATH=src python -m unittest tests.test_live.LiveTest.test_openai

# Ask the default OpenAI model. Set OPENAI_API_KEY in the environment first.
ask question:
    PYTHONPATH=src python -c 'import sys; from llm_ai_api import llm; print(llm("openai:gpt-6-luna").ask(sys.argv[1]))' '{{question}}'
