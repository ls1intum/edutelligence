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
