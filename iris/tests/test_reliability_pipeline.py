"""AbstractAgentPipeline and the watchdog: run registration and stopping a closed run."""

# pylint: disable=protected-access
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.pipeline.abstract_agent_pipeline import AbstractAgentPipeline  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.reliability import run_registry as registry_module  # noqa: E402
from iris.reliability.run_registry import RunRegistry  # noqa: E402


class _MiniPipeline(AbstractAgentPipeline):
    """Smallest agent pipeline: the base class __call__ with no tools."""

    def __call__(
        self, dto, variant, callback, local=False
    ):  # pylint: disable=useless-parent-delegation
        return super().__call__(dto, variant, callback, local)

    def get_tools(self, state):  # pylint: disable=unused-argument
        return []

    def build_system_message(self, state):  # pylint: disable=unused-argument
        return "system"


def _run(pipeline, callback, execute_agent, registry=None, seen=None):
    variant = SimpleNamespace(id="default", model=lambda _role, _local: "m")
    registry = registry if registry is not None else RunRegistry()
    seen = seen if seen is not None else {}
    with (
        patch.object(registry_module, "run_registry", registry),
        patch("iris.pipeline.abstract_agent_pipeline.run_registry", registry),
        patch("iris.pipeline.abstract_agent_pipeline.VectorDatabase"),
        patch("iris.pipeline.abstract_agent_pipeline.LlmRequestHandler"),
        patch("iris.pipeline.abstract_agent_pipeline.IrisLangchainChatModel"),
        patch.object(pipeline, "_load_history", return_value=[]),
        patch.object(pipeline, "create_tracing_context", return_value=None),
        patch.object(pipeline, "_update_langfuse_trace"),
        patch.object(pipeline, "execute_agent", side_effect=execute_agent),
        patch.object(pipeline, "post_agent_hook") as post_agent_hook,
        patch.object(pipeline, "_start_compaction") as start_compaction,
    ):

        def capture_and_run(state):
            seen["runs"] = registry.snapshot()
            return execute_agent(state)

        pipeline.execute_agent.side_effect = capture_and_run
        try:
            pipeline(dto=SimpleNamespace(), variant=variant, callback=callback)
        finally:
            seen["after"] = registry.snapshot()
    return seen, post_agent_hook, start_compaction


def test_a_run_is_registered_while_it_runs_and_removed_when_it_raises():
    callback = MagicMock(closed_by_watchdog=False)

    def boom(state):  # pylint: disable=unused-argument
        raise RuntimeError("agent failed")

    registry, seen = RunRegistry(), {}
    with pytest.raises(RuntimeError):
        _run(_MiniPipeline(), callback, boom, registry=registry, seen=seen)

    assert len(seen["runs"]) == 1
    assert not registry.snapshot()


def test_registration_and_cleanup():
    callback = MagicMock(closed_by_watchdog=False)
    seen, post_agent_hook, _ = _run(_MiniPipeline(), callback, lambda _s: "answer")

    assert len(seen["runs"]) == 1
    assert seen["runs"][0].deadline_seconds is None  # only chat waits for an answer
    assert seen["after"] == []
    post_agent_hook.assert_called_once()


def test_a_run_closed_by_the_watchdog_skips_the_post_agent_work():
    callback = MagicMock(closed_by_watchdog=False)

    def closed_meanwhile(state):  # pylint: disable=unused-argument
        callback.closed_by_watchdog = True
        return "late answer"

    seen, post_agent_hook, start_compaction = _run(
        _MiniPipeline(), callback, closed_meanwhile
    )

    post_agent_hook.assert_not_called()
    start_compaction.assert_not_called()
    callback.finish.assert_not_called()
    assert seen["after"] == []


def test_only_the_chat_pipeline_has_an_answer_deadline():
    assert ChatPipeline.ANSWER_DEADLINE is True
    assert AbstractAgentPipeline.ANSWER_DEADLINE is False
