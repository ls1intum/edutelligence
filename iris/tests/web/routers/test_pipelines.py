import threading
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO
from iris.pipeline.chat.ask_user_pipeline import AskUserPipeline as RealAskUserPipeline
from iris.tracing import TracedThreadPoolExecutor
from iris.web.routers.pipelines import (
    get_pipeline,
    run_ask_user_pipeline,
    run_ask_user_pipeline_worker,
)


def _dto(variant="default", selection="CLOUD_AI"):
    settings = PipelineExecutionSettingsDTO(
        authenticationToken="token-1",
        artemisBaseUrl="https://artemis.example",
        variant=variant,
        selection=selection,
    )
    return SimpleNamespace(settings=settings)


def _patch_ask_user_pipeline_class(pipeline_instance=None):
    """Patch the AskUserPipeline symbol used by the router while keeping
    get_variants() delegating to the real implementation, since
    find_variant() depends on it returning real AskUserVariant objects."""
    patcher = patch("iris.web.routers.pipelines.AskUserPipeline")
    pipeline_cls = patcher.start()
    pipeline_cls.get_variants = RealAskUserPipeline.get_variants
    if pipeline_instance is not None:
        pipeline_cls.return_value = pipeline_instance
    return patcher, pipeline_cls


# --------------------------------------------------------------------------
# get_pipeline("ASK_USER")
# --------------------------------------------------------------------------


def test_get_pipeline_ask_user_returns_ask_user_variants():
    features = get_pipeline("ASK_USER")

    ids = {feature.id for feature in features}
    assert ids == {"default", "advanced"}


# --------------------------------------------------------------------------
# run_ask_user_pipeline (the POST endpoint body)
# --------------------------------------------------------------------------


def test_run_ask_user_pipeline_submits_worker_to_dedicated_executor():
    dto = _dto()

    with patch("iris.web.routers.pipelines._ask_user_executor") as executor:
        run_ask_user_pipeline(event="FIRST_QUESTION", dto=dto)

    executor.submit.assert_called_once()
    args = executor.submit.call_args.args
    assert args[0] is run_ask_user_pipeline_worker
    assert args[1] is dto
    assert args[2] == "default"  # validated variant id
    assert args[3] == "FIRST_QUESTION"  # event


def test_run_ask_user_pipeline_forwards_none_event():
    # FastAPI resolves the Query(None, ...) default to None at request time;
    # calling the handler directly, we exercise that forwarding explicitly.
    dto = _dto()

    with patch("iris.web.routers.pipelines._ask_user_executor") as executor:
        run_ask_user_pipeline(event=None, dto=dto)

    args = executor.submit.call_args.args
    assert args[3] is None


# --------------------------------------------------------------------------
# _ask_user_executor concurrency
# --------------------------------------------------------------------------


def test_ask_user_executor_max_workers_is_configurable():
    from iris.config import settings as app_settings
    from iris.web.routers import pipelines as pipelines_module

    assert (
        pipelines_module._ask_user_executor._max_workers  # pylint: disable=protected-access
        == app_settings.pipelines.ask_user_max_workers
    )
    assert app_settings.pipelines.ask_user_max_workers > 1


def test_ask_user_executor_runs_multiple_sessions_concurrently():
    """A single slow submission must not block other queued submissions
    behind it (regression test for the single-worker serialization bug)."""
    executor = TracedThreadPoolExecutor(max_workers=3)
    started = threading.Barrier(3, timeout=5)

    def slow_task():
        started.wait()  # only completes once 3 tasks are running at once
        return "done"

    try:
        futures: list[Future] = [executor.submit(slow_task) for _ in range(3)]
        results = [f.result(timeout=5) for f in futures]
    finally:
        executor.shutdown(wait=True)

    assert results == ["done", "done", "done"]


def test_ask_user_executor_with_single_worker_would_serialize_and_deadlock():
    """Sanity check proving the old max_workers=1 configuration is exactly
    the bug being fixed: three sessions can never all be in-flight at once,
    so a barrier waiting for 3 concurrent starts would hang."""
    executor = TracedThreadPoolExecutor(max_workers=1)
    started = threading.Barrier(3, timeout=0.5)

    def slow_task():
        started.wait()

    try:
        futures = [executor.submit(slow_task) for _ in range(3)]
        with_timeout_errors = 0
        for f in futures:
            try:
                f.result(timeout=1)
            except Exception:  # pylint: disable=broad-except
                with_timeout_errors += 1
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # The barrier can never fill with only one worker running at a time.
    assert with_timeout_errors > 0


# --------------------------------------------------------------------------
# run_ask_user_pipeline_worker
# --------------------------------------------------------------------------


def test_worker_gives_up_quietly_when_callback_creation_fails():
    dto = _dto()

    patcher, pipeline_cls = _patch_ask_user_pipeline_class()
    try:
        with (
            patch(
                "iris.web.routers.pipelines.AskUserStatusCallback",
                side_effect=RuntimeError("no auth token"),
            ),
            patch("iris.web.routers.pipelines.capture_exception") as capture,
        ):
            run_ask_user_pipeline_worker(dto, "default", "FIRST_QUESTION", "req-1")
    finally:
        patcher.stop()

    pipeline_cls.assert_not_called()
    capture.assert_called_once()


def test_worker_fails_callback_when_variant_is_unknown():
    dto = _dto()
    callback = MagicMock()

    patcher, pipeline_cls = _patch_ask_user_pipeline_class()
    try:
        with patch(
            "iris.web.routers.pipelines.AskUserStatusCallback", return_value=callback
        ):
            run_ask_user_pipeline_worker(dto, "does-not-exist", None, "req-1")
    finally:
        patcher.stop()

    pipeline_cls.assert_not_called()
    callback.fail.assert_called_once()
    assert callback.fail.call_args.args[0] == "Fatal error."
    assert isinstance(callback.fail.call_args.kwargs["exception"], ValueError)


def test_worker_runs_pipeline_with_resolved_variant_on_success():
    dto = _dto()
    callback = MagicMock()
    pipeline_instance = MagicMock()

    patcher, pipeline_cls = _patch_ask_user_pipeline_class(pipeline_instance)
    try:
        with patch(
            "iris.web.routers.pipelines.AskUserStatusCallback", return_value=callback
        ):
            run_ask_user_pipeline_worker(dto, "advanced", "FIRST_QUESTION", "req-1")
    finally:
        patcher.stop()

    # AskUserVariant has no __eq__, so the resolved variant is compared by id.
    init_kwargs = pipeline_cls.call_args.kwargs
    assert init_kwargs["local"] is False
    assert init_kwargs["variant"].id == "advanced"
    assert init_kwargs["variant"].agent_model == "oai-gpt-52"
    call_kwargs = pipeline_instance.call_args.kwargs
    assert call_kwargs["dto"] is dto
    assert call_kwargs["callback"] is callback
    assert call_kwargs["event"] == "FIRST_QUESTION"
    assert call_kwargs["variant"].id == "advanced"
    assert call_kwargs["variant"].agent_model == "oai-gpt-52"
    callback.fail.assert_not_called()


def test_worker_constructs_pipeline_with_local_flag_for_local_ai_selection():
    dto = _dto(selection="LOCAL_AI")
    callback = MagicMock()
    pipeline_instance = MagicMock()

    patcher, pipeline_cls = _patch_ask_user_pipeline_class(pipeline_instance)
    try:
        with patch(
            "iris.web.routers.pipelines.AskUserStatusCallback", return_value=callback
        ):
            run_ask_user_pipeline_worker(dto, "default", "FIRST_QUESTION", "req-1")
    finally:
        patcher.stop()

    init_kwargs = pipeline_cls.call_args.kwargs
    assert init_kwargs["local"] is True
    assert init_kwargs["variant"].id == "default"
    callback.fail.assert_not_called()


def test_worker_fails_callback_when_pipeline_execution_raises():
    dto = _dto()
    callback = MagicMock()
    pipeline_instance = MagicMock(side_effect=RuntimeError("pipeline exploded"))

    patcher, _pipeline_cls = _patch_ask_user_pipeline_class(pipeline_instance)
    try:
        with patch(
            "iris.web.routers.pipelines.AskUserStatusCallback", return_value=callback
        ):
            run_ask_user_pipeline_worker(dto, "default", None, "req-1")
    finally:
        patcher.stop()

    callback.fail.assert_called_once()
    assert callback.fail.call_args.args[0] == "Fatal error."
