from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO
from iris.pipeline.chat.ask_user_pipeline import AskUserPipeline as RealAskUserPipeline
from iris.web.routers.pipelines import (
    get_pipeline,
    run_prompt_user_pipeline,
    run_prompt_user_pipeline_worker,
)


def _dto(variant="default"):
    settings = PipelineExecutionSettingsDTO(
        authenticationToken="token-1",
        artemisBaseUrl="https://artemis.example",
        variant=variant,
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
# get_pipeline("PROMPT_USER")
# --------------------------------------------------------------------------


def test_get_pipeline_prompt_user_returns_ask_user_variants():
    features = get_pipeline("PROMPT_USER")

    ids = {feature.id for feature in features}
    assert ids == {"default", "advanced"}


# --------------------------------------------------------------------------
# run_prompt_user_pipeline (the POST endpoint body)
# --------------------------------------------------------------------------


def test_run_prompt_user_pipeline_submits_worker_to_dedicated_executor():
    dto = _dto()

    with patch("iris.web.routers.pipelines._prompt_user_executor") as executor:
        run_prompt_user_pipeline(event="FIRST_QUESTION", dto=dto)

    executor.submit.assert_called_once()
    args = executor.submit.call_args.args
    assert args[0] is run_prompt_user_pipeline_worker
    assert args[1] is dto
    assert args[2] == "default"  # validated variant id
    assert args[3] == "FIRST_QUESTION"  # event


def test_run_prompt_user_pipeline_forwards_none_event():
    # FastAPI resolves the Query(None, ...) default to None at request time;
    # calling the handler directly, we exercise that forwarding explicitly.
    dto = _dto()

    with patch("iris.web.routers.pipelines._prompt_user_executor") as executor:
        run_prompt_user_pipeline(event=None, dto=dto)

    args = executor.submit.call_args.args
    assert args[3] is None


# --------------------------------------------------------------------------
# run_prompt_user_pipeline_worker
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
            run_prompt_user_pipeline_worker(dto, "default", "FIRST_QUESTION", "req-1")
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
            run_prompt_user_pipeline_worker(dto, "does-not-exist", None, "req-1")
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
            run_prompt_user_pipeline_worker(dto, "advanced", "FIRST_QUESTION", "req-1")
    finally:
        patcher.stop()

    pipeline_cls.assert_called_once_with()
    call_kwargs = pipeline_instance.call_args.kwargs
    assert call_kwargs["dto"] is dto
    assert call_kwargs["callback"] is callback
    assert call_kwargs["event"] == "FIRST_QUESTION"
    # AskUserVariant has no __eq__, so the resolved variant is compared by id.
    assert call_kwargs["variant"].id == "advanced"
    assert call_kwargs["variant"].agent_model == "oai-gpt-52"
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
            run_prompt_user_pipeline_worker(dto, "default", None, "req-1")
    finally:
        patcher.stop()

    callback.fail.assert_called_once()
    assert callback.fail.call_args.args[0] == "Fatal error."
