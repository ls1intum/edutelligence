from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from iris.tracing.langfuse_tracer import observe


def test_observe_does_not_execute_business_function_twice_after_error():
    business_function = Mock(side_effect=RuntimeError("business error"))
    langfuse = SimpleNamespace(
        observe=lambda **_kwargs: lambda function: function,
    )

    with (
        patch(
            "iris.tracing.langfuse_tracer._get_langfuse_module",
            return_value=langfuse,
        ),
        patch("iris.tracing.langfuse_tracer._is_enabled", return_value=True),
    ):
        observed = observe()(business_function)

        with pytest.raises(RuntimeError, match="business error"):
            observed()

    business_function.assert_called_once_with()


def test_observe_falls_back_once_when_tracing_setup_fails():
    business_function = Mock(return_value="result")
    langfuse = SimpleNamespace(observe=Mock(side_effect=RuntimeError("setup error")))

    with (
        patch(
            "iris.tracing.langfuse_tracer._get_langfuse_module",
            return_value=langfuse,
        ),
        patch("iris.tracing.langfuse_tracer._is_enabled", return_value=True),
    ):
        observed = observe()(business_function)

        assert observed() == "result"

    business_function.assert_called_once_with()


def test_tracing_context_keeps_credentials_and_names_out_of_traces():
    from iris.tracing.langfuse_tracer import (  # pylint: disable=import-outside-toplevel
        TracingContext,
    )

    dto = SimpleNamespace(
        user=SimpleNamespace(id=42, first_name="Ada", last_name="Lovelace"),
        settings=SimpleNamespace(
            authentication_token="secret-callback-token",
            artemis_base_url="https://artemis.example",
        ),
    )

    params = TracingContext.from_dto(dto, "ChatPipeline").to_langfuse_params()

    assert params["user_id"] == "42"
    assert "secret-callback-token" not in str(params)
    assert "Ada" not in str(params) and "Lovelace" not in str(params)


def test_observe_does_not_export_inputs_that_carry_credentials_or_names():
    captured = []

    def fake_observe(**kwargs):
        captured.append(kwargs)
        return lambda function: function

    langfuse = SimpleNamespace(observe=fake_observe)
    dto = SimpleNamespace(
        settings=SimpleNamespace(authentication_token="sentinel-token"),
        user=SimpleNamespace(first_name="Ada", last_name="Lovelace"),
    )
    callback = SimpleNamespace(run_id="sentinel-token", url="https://artemis.example")

    @observe(name="pipeline")
    def pipeline(dto_argument, callback_argument=None):
        del dto_argument, callback_argument
        return "ok"

    @observe(name="retrieval")
    def retrieval(query):
        return query

    with (
        patch(
            "iris.tracing.langfuse_tracer._get_langfuse_module",
            return_value=langfuse,
        ),
        patch("iris.tracing.langfuse_tracer._is_enabled", return_value=True),
    ):
        assert pipeline(dto) == "ok"
        assert pipeline("plain", callback_argument=callback) == "ok"
        assert retrieval("what is a heap?") == "what is a heap?"

    assert [call["capture_input"] for call in captured] == [False, False, True]


def test_observe_detects_credentials_nested_in_an_execution_state():
    from iris.tracing.langfuse_tracer import (  # pylint: disable=import-outside-toplevel
        carries_sensitive_data,
    )

    class _State:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.dto = SimpleNamespace(
                settings=SimpleNamespace(authentication_token="sentinel-token")
            )
            self.result = "draft"

    class _CallbackOnly:  # pylint: disable=too-few-public-methods
        def __init__(self):
            self.callback = SimpleNamespace(run_id="sentinel-token", url="https://a")

    assert carries_sensitive_data((_State(),), {})
    assert carries_sensitive_data((), {"state": _CallbackOnly()})
    assert carries_sensitive_data(([{"user": SimpleNamespace(last_name="L")}],), {})
    assert not carries_sensitive_data(("query", 3, ["a", "b"]), {"limit": 5})
