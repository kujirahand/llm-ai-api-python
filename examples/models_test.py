"""Let two models from different providers discuss this morning's breakfast menu.

Uses the constants in `llm_ai_api.models`. Needs both OPENAI_API_KEY and ANTHROPIC_API_KEY.

Usage: python examples/models_test.py [ROUNDS]
"""

import sys

from llm_ai_api import LLMError, llm, models

TOPIC = "this morning's breakfast menu"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def messages_for(me, transcript):
    """Build the history from `me`'s point of view: my lines are 'assistant', theirs are 'user'."""
    msgs = []
    for name, text in transcript:
        role = "assistant" if name == me else "user"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + text
        else:
            msgs.append({"role": role, "content": text})
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": "Let's talk about %s. Please start." % TOPIC})
    return msgs


def system_for(me, other):
    return (
        "You are %s, chatting with %s about %s. Share your own opinion in 2-3 sentences, "
        "react to what they said, and do not repeat yourself. Reply with your own words only."
        % (me, other, TOPIC)
    )


def main():
    print("Topic: %s\n" % TOPIC)
    transcript = []
    try:
        # Created inside `try` so that a missing API key is reported as a short message.
        speakers = {
            "Luna": llm(models.OPENAI_GPT6_LUNA, max_tokens=300),
            "Haiku": llm(models.ANTHROPIC_CLAUDE_HAIKU_5_5, max_tokens=300),
        }
        names = list(speakers)
        for turn in range(ROUNDS * 2):
            me, other = names[turn % 2], names[(turn + 1) % 2]
            reply = speakers[me].chat(
                messages_for(me, transcript), system=system_for(me, other)
            ).text.strip()
            transcript.append((me, reply))
            print("%s: %s\n" % (me, reply))
    except LLMError as e:
        sys.exit(str(e))


main()
