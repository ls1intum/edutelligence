"""Ollama models whose template accepts a system message only at the start."""

# pylint: skip-file

from unittest.mock import MagicMock

from ollama import Message  # noqa: E402

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.ollama import (  # noqa: E402
    OllamaModel,
    keep_ollama_system_messages_leading,
)


def _roles_and_text(messages):
    return [(message.role, message.content) for message in messages]


def test_trailing_system_message_becomes_marked_user_message_in_place():
    rewritten = keep_ollama_system_messages_leading(
        [
            Message(role="system", content="prompt"),
            Message(role="system", content="more prompt"),
            Message(role="user", content="question"),
            Message(role="system", content="Current Date: today"),
        ]
    )

    assert _roles_and_text(rewritten) == [
        ("system", "prompt\nmore prompt"),
        ("user", "question"),
        ("user", "[System note]\nCurrent Date: today"),
    ]


def test_lone_system_prompt_is_sent_as_user_message():
    rewritten = keep_ollama_system_messages_leading(
        [Message(role="system", content="only")]
    )

    assert _roles_and_text(rewritten) == [("user", "only")]


def _message(sender, text):
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


def _chat_roles(leading_system_message_only):
    model = OllamaModel(
        id="qwen-local",
        type="ollama",
        model="qwen3",
        host="http://localhost:11434",
        leading_system_message_only=leading_system_message_only,
    )
    client = MagicMock()
    client.chat.return_value = {
        "message": {"role": "assistant", "content": "ok"},
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    model._client = client
    model.chat(
        [
            _message(IrisMessageRole.SYSTEM, "prompt"),
            _message(IrisMessageRole.USER, "question"),
            _message(IrisMessageRole.SYSTEM, "context"),
        ],
        CompletionArguments(),
        None,
    )
    return [message.role for message in client.chat.call_args.kwargs["messages"]]


def test_chat_applies_the_rewrite_only_when_the_flag_is_set():
    assert _chat_roles(True) == ["system", "user", "user"]
    assert _chat_roles(False) == ["system", "user", "system"]
