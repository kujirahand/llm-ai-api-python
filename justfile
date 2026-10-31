# Run the unit test suite.
test:
    PYTHONPATH=src python -m unittest discover -s tests -t .

# Ask the default OpenAI model. Set OPENAI_API_KEY in the environment first.
ask question:
    PYTHONPATH=src python -c 'import sys; from llm_ai_api import llm; print(llm("openai:gpt-6-luna").ask(sys.argv[1]))' '{{question}}'
