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
from iris.web.status.status_update import RunPhase  # noqa: E402


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


def _run(  # pylint: disable=too-many-arguments
    pipeline, callback, execute_agent, registry=None, seen=None, post_hook=None
):
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
        patch.object(
            pipeline, "post_agent_hook", side_effect=post_hook
        ) as post_agent_hook,
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
    # Not terminal yet: the caller still sends the FAILED, so the run stays visible
    # (as orphaned) until the watchdog sees that frame go out.
    records = registry.snapshot()
    assert len(records) == 1 and records[0].orphaned is True


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


def test_a_run_closed_during_the_first_status_post_does_no_work():
    callback = MagicMock(closed_by_watchdog=False)
    registry, seen = RunRegistry(), {}

    def slow_first_post(**_fields):
        seen["runs_during_update"] = registry.snapshot()
        callback.closed_by_watchdog = True

    callback.update.side_effect = slow_first_post
    execute_agent = MagicMock(return_value="answer")

    _run(_MiniPipeline(), callback, execute_agent, registry=registry, seen=seen)

    assert len(seen["runs_during_update"]) == 1  # visible to the watchdog already
    execute_agent.assert_not_called()
    assert not registry.snapshot()


def test_a_run_closed_during_the_post_agent_hook_does_not_finish():
    callback = MagicMock(closed_by_watchdog=False)

    def closed_in_hook(state):  # pylint: disable=unused-argument
        callback.closed_by_watchdog = True

    _run(_MiniPipeline(), callback, lambda _s: "answer", post_hook=closed_in_hook)

    callback.finish.assert_not_called()


def test_a_run_closed_during_preparation_does_not_start_the_agent():
    callback = MagicMock(closed_by_watchdog=False)
    pipeline = _MiniPipeline()
    execute_agent = MagicMock(return_value="answer")

    def closing_pre_hook(state):  # pylint: disable=unused-argument
        callback.closed_by_watchdog = True

    with patch.object(pipeline, "pre_agent_hook", side_effect=closing_pre_hook):
        _run(pipeline, callback, execute_agent)

    execute_agent.assert_not_called()


def test_a_run_closed_before_the_pre_agent_hook_does_not_run_it():
    callback = MagicMock(closed_by_watchdog=False)
    pipeline = _MiniPipeline()

    def closing_prepare(state):  # pylint: disable=unused-argument
        callback.closed_by_watchdog = True

    with (
        patch.object(pipeline, "prepare_state", side_effect=closing_prepare),
        patch.object(pipeline, "pre_agent_hook") as pre_agent_hook,
    ):
        _run(pipeline, callback, MagicMock(return_value="answer"))

    pre_agent_hook.assert_not_called()


def test_the_pipeline_hands_its_usage_list_to_the_callback():
    callback = MagicMock(closed_by_watchdog=False)
    pipeline = _MiniPipeline()

    _run(pipeline, callback, lambda _s: "answer")

    callback.attach_usage.assert_called_once_with(pipeline.tokens)


def test_mcq_generation_is_not_started_for_a_run_closed_during_retrieval():
    from iris.pipeline.chat import (  # pylint: disable=import-outside-toplevel
        mcq_chat_mixin,
    )

    callback = MagicMock(closed_by_watchdog=False)
    state = SimpleNamespace(
        mcq_parallel=True,
        callback=callback,
        dto=SimpleNamespace(settings=None, user=SimpleNamespace(lang_key="en")),
    )
    mcq_pipeline = MagicMock()

    def closing_retrieval(*_args, **_kwargs):
        callback.closed_by_watchdog = True
        return [], None

    with patch.object(
        mcq_chat_mixin,
        "retrieve_lecture_content_for_mcq",
        side_effect=closing_retrieval,
    ):
        mcq_chat_mixin.mcq_pre_agent_hook(
            state,
            mcq_pipeline,
            lambda _s: "quiz me",
            db=None,
            course_id=1,
            chat_history=[],
        )

    mcq_pipeline.run_in_thread.assert_not_called()


def test_a_run_that_raised_after_its_terminal_frame_is_unregistered_at_once():
    callback = MagicMock(closed_by_watchdog=False)
    registry, seen = RunRegistry(), {}

    def finish_then_boom(state):  # pylint: disable=unused-argument
        callback.phase = RunPhase.TERMINAL
        raise RuntimeError("after the end")

    with pytest.raises(RuntimeError):
        _run(_MiniPipeline(), callback, finish_then_boom, registry=registry, seen=seen)

    assert not registry.snapshot()


def test_runs_started_during_a_restart_are_failed_at_once():
    callback = MagicMock(closed_by_watchdog=False)
    registry = RunRegistry()
    registry.refusal = ("Iris had to restart. Please try again.", "restart")
    execute_agent = MagicMock(return_value="answer")

    _run(_MiniPipeline(), callback, execute_agent, registry=registry)

    callback.fail.assert_called_once_with(
        "Iris had to restart. Please try again.", code="restart"
    )
    execute_agent.assert_not_called()
    assert not registry.snapshot()


def test_a_run_whose_terminal_post_is_still_in_flight_stays_visible():
    callback = MagicMock(closed_by_watchdog=False, terminal_post_in_flight=True)
    registry = RunRegistry()

    _run(_MiniPipeline(), callback, lambda _s: "answer", registry=registry)

    records = registry.snapshot()
    assert len(records) == 1 and records[0].orphaned is True


def test_without_a_watchdog_no_run_is_kept():
    from iris.config import settings  # pylint: disable=import-outside-toplevel

    callback = MagicMock(closed_by_watchdog=False)
    registry = RunRegistry()

    def boom(state):  # pylint: disable=unused-argument
        raise RuntimeError("agent failed")

    with patch.object(settings.reliability, "enabled", False):
        with pytest.raises(RuntimeError):
            _run(_MiniPipeline(), callback, boom, registry=registry)

    assert not registry.snapshot()


def test_every_run_is_either_in_the_closing_snapshot_or_refused():
    import threading  # pylint: disable=import-outside-toplevel

    for _ in range(20):
        registry = RunRegistry()
        outcomes = {}
        start = threading.Barrier(9)

        def start_run(index, reg, barrier, out):
            record = SimpleNamespace(index=index)
            barrier.wait()
            out[index] = (record, reg.admit(record))

        threads = [
            threading.Thread(target=start_run, args=(i, registry, start, outcomes))
            for i in range(8)
        ]
        for thread in threads:
            thread.start()
        start.wait()
        snapshot = registry.refuse_and_snapshot(("restart", "restart"))
        for thread in threads:
            thread.join(5)

        for record, refusal in outcomes.values():
            assert (record in snapshot) != (refusal is not None)
