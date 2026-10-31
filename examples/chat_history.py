"""Reply based on a chat history.

The library keeps no conversation state: you pass the whole history on every
call and append the reply yourself.

Usage: python examples/chat_history.py PROVIDER:MODEL
"""

from _common import get_model_spec

from llm_ai_api import llm

m = llm(get_model_spec(), system="You are a friendly assistant. Keep answers short.")

history = [
    {"role": "user", "content": "Hi! My dog is called Pochi."},
    {"role": "assistant", "content": "Nice to meet you! Pochi is a lovely name."},
    {"role": "user", "content": "What is my dog's name?"},
]

result = m.chat(history)
print("assistant:", result.text)

# Continue the conversation: append the reply, then the next question.
history.append({"role": "assistant", "content": result.text})
history.append({"role": "user", "content": "Suggest a toy for Pochi."})
print("assistant:", m.chat(history).text)
