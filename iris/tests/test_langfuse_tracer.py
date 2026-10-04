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
