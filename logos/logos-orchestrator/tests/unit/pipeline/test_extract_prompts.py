"""RequestPipeline._extract_prompts: Chat Completions and Responses shapes."""

from logos.pipeline.pipeline import RequestPipeline


def _extract(payload):
    # _extract_prompts does not touch self; call unbound to avoid building a
    # full pipeline.
    return RequestPipeline._extract_prompts(None, payload)


def test_chat_messages_extracted():
    user, system = _extract(
        {
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hello"},
            ]
        }
    )
    assert (user, system) == ("hello", "be brief")


def test_responses_string_input_with_instructions():
    user, system = _extract({"input": "hello", "instructions": "be brief"})
    assert (user, system) == ("hello", "be brief")


def test_responses_message_list_input():
    user, system = _extract(
        {
            "input": [
                {"role": "developer", "content": "be brief"},
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello"}],
                },
            ]
        }
    )
    assert (user, system) == ("hello", "be brief")


def test_messages_take_precedence_over_input():
    user, system = _extract(
        {
            "messages": [{"role": "user", "content": "from messages"}],
            "input": "from input",
        }
    )
    assert (user, system) == ("from messages", "")
