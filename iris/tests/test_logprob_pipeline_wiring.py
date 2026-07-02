from types import SimpleNamespace
from unittest.mock import patch

# Establish module import order (see note in other tests).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import (  # noqa: E402
    IrisMessageRole,
    PyrisAIMessage,
    PyrisMessage,
)
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.langchain.iris_langchain_chat_model import (  # noqa: E402
    IrisLangchainChatModel,
)
from iris.llm.request_handler.request_handler_interface import (  # noqa: E402
    RequestHandler,
)
from iris.pipeline.autonomous_tutor_pipeline import (  # noqa: E402
    AutonomousTutorPipeline,
)


class _StubRequestHandler(RequestHandler):
    """Minimal RequestHandler whose chat() returns a preset message."""

    next_message: object = None

    def complete(self, prompt, arguments, image=None):
        raise NotImplementedError

    def chat(self, messages, arguments, tools):
        return self.next_message

    def embed(self, text):
        raise NotImplementedError

    def bind_tools(self, tools):
        return self


def _text_message(text, token_logprobs=None):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(textContent=text)],
        token_logprobs=token_logprobs,
    )


# ──────────────────────────────────────────────────────────────────────────
# IrisLangchainChatModel captures the final answer's logprobs
# ──────────────────────────────────────────────────────────────────────────
def test_generate_captures_token_logprobs_from_text_message():
    handler = _StubRequestHandler()
    handler.next_message = _text_message("hello", token_logprobs=[-0.1, -0.2])
    model = IrisLangchainChatModel(
        request_handler=handler, completion_args=CompletionArguments()
    )
    model._generate(messages=[])  # pylint: disable=protected-access
    assert model.last_token_logprobs == [-0.1, -0.2]


def test_tool_call_turn_does_not_overwrite_final_logprobs():
    handler = _StubRequestHandler()
    model = IrisLangchainChatModel(
        request_handler=handler, completion_args=CompletionArguments()
    )

    # First, a text generation with logprobs (the "answer").
    handler.next_message = _text_message("answer", token_logprobs=[-0.3])
    model._generate(messages=[])  # pylint: disable=protected-access
    assert model.last_token_logprobs == [-0.3]

    # Then a tool-call turn (empty content) must not clear the captured value.
    handler.next_message = PyrisAIMessage(
        tool_calls=[],
        contents=[TextMessageContentDTO(textContent="")],
        token_logprobs=None,
    )
    model._generate(messages=[])  # pylint: disable=protected-access
    assert model.last_token_logprobs == [-0.3]


# ──────────────────────────────────────────────────────────────────────────
# AutonomousTutorPipeline strategy selection
# ──────────────────────────────────────────────────────────────────────────
def _make_pipeline():
    return AutonomousTutorPipeline()


def _fake_state(model_name="gpt-test"):
    llm = SimpleNamespace(
        model_name=model_name,
        completion_args=CompletionArguments(),
        last_token_logprobs=None,
    )
    return SimpleNamespace(llm=llm, result="")


def test_prepare_state_enables_logprobs_when_supported():
    pipeline = _make_pipeline()
    state = _fake_state()
    with patch(
        "iris.pipeline.autonomous_tutor_pipeline.model_supports_logprobs",
        return_value=True,
    ):
        pipeline.prepare_state(state)
    assert state.use_logprob_confidence is True
    assert state.llm.completion_args.logprobs is True


def test_prepare_state_falls_back_when_unsupported():
    pipeline = _make_pipeline()
    state = _fake_state()
    with patch(
        "iris.pipeline.autonomous_tutor_pipeline.model_supports_logprobs",
        return_value=False,
    ):
        pipeline.prepare_state(state)
    assert state.use_logprob_confidence is False
    assert state.llm.completion_args.logprobs is False


def test_estimate_confidence_uses_logprobs_and_keeps_answer_intact():
    pipeline = _make_pipeline()
    state = _fake_state()
    state.use_logprob_confidence = True
    state.llm.last_token_logprobs = [0.0, 0.0]
    state.result = "The answer is 42."
    confidence = pipeline._estimate_confidence(  # pylint: disable=protected-access
        state
    )
    assert confidence == 1.0
    # logprob mode must not strip/mutate the answer text
    assert state.result == "The answer is 42."


def test_estimate_confidence_verbalized_path_parses_and_strips():
    pipeline = _make_pipeline()
    state = _fake_state()
    state.use_logprob_confidence = False
    state.result = "Answer: hi there\nProbability: 0.9"
    confidence = pipeline._estimate_confidence(  # pylint: disable=protected-access
        state
    )
    assert confidence == 0.9
    assert "Probability" not in state.result
    assert "hi there" in state.result
