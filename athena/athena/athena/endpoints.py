from http.client import HTTPException
import inspect
from fastapi import Depends, BackgroundTasks, Body, Request
from pydantic import ConfigDict, BaseModel, ValidationError
from pydantic.alias_generators import to_camel
from typing import Dict, TypeVar, Callable, List, Union, Any, Coroutine, Type, Optional

from athena.app import app
from athena.authenticate import authenticated
from athena.metadata import with_meta
from athena.module_config import (
    get_header_module_config_factory,
    get_default_module_config_from_app_factory,
    get_dynamic_module_config_factory,
)
from athena.logger import logger
from athena.schemas import Exercise, Submission, Feedback, LearnerProfile
from athena.storage import get_stored_submission_meta, get_stored_exercise_meta, get_stored_feedback_meta, \
    store_exercise, store_feedback, store_feedback_suggestions, store_submissions, get_stored_submissions

E = TypeVar("E", bound=Exercise)
S = TypeVar("S", bound=Submission)
F = TypeVar("F", bound=Feedback)
G = TypeVar("G", bound=bool)
C = TypeVar("C", bound=BaseModel)

module_responses = {
    403: {
        "description": "API secret is invalid - set the environment variable SECRET and the Authorization header "
        "to the same value",
    }
}


def submissions_consumer(
    func: Union[
        Callable[[E, List[S]], None],
        Callable[[E, List[S]], Coroutine[Any, Any, None]],
        Callable[[E, List[S], C], None],
        Callable[[E, List[S], C], Coroutine[Any, Any, None]],
    ],
):
    """
    Receive submissions from the Assessment Module Manager.
    The submissions consumer is usually called whenever the deadline for an exercise is reached.

    This decorator can be used with several types of functions: synchronous or asynchronous, with or without a module config.

    Examples:
        Below are some examples of possible functions that you can decorate with this decorator:

        Without using module config (both synchronous and asynchronous forms):
        >>> @submissions_consumer
        ... def sync_receive_submissions(exercise: Exercise, submissions: List[Submission]):
        ...     # process submissions synchronously here

        >>> @submissions_consumer
        ... async def async_receive_submissions(exercise: Exercise, submissions: List[Submission]):
        ...     # process submissions asynchronously here

        With using module config (both synchronous and asynchronous forms):
        >>> @submissions_consumer
        ... def sync_receive_submissions_with_config(exercise: Exercise, submissions: List[Submission], module_config: Optional[dict]):
        ...     # process submissions synchronously here using module_config

        >>> @submissions_consumer
        ... async def async_receive_submissions_with_config(exercise: Exercise, submissions: List[Submission], module_config: Optional[dict]):
        ...     # process submissions asynchronously here using module_config
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = (
        inspect.signature(func).parameters["submissions"].annotation.__args__[0]
    )
    module_config_type = (
        inspect.signature(func).parameters["module_config"].annotation
        if "module_config" in inspect.signature(func).parameters
        else Any
    )

    @app.post("/submissions", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
        background_tasks: BackgroundTasks,
        exercise: exercise_type,
        submissions: List[submission_type],
        module_config: module_config_type = Depends(
            get_dynamic_module_config_factory(module_config_type)
        ),
    ):

        # Retrieve existing metadata for the exercise and submissions
        exercise_meta = get_stored_exercise_meta(exercise) or {}
        exercise_meta.update(exercise.meta)
        exercise.meta = exercise_meta
        submissions_dict = {s.id: s for s in submissions}
        if submissions:
            stored_submissions = get_stored_submissions(
                submissions[0].__class__, exercise.id, [s.id for s in submissions]
            )
            for stored_submission in stored_submissions:
                if stored_submission.id in submissions_dict:
                    submission_meta = (
                        get_stored_submission_meta(stored_submission) or {}
                    )
                    submission_meta.update(stored_submission.meta)
                    submissions_dict[stored_submission.id].meta = submission_meta

        kwargs = {}
        if "module_config" in inspect.signature(func).parameters:
            kwargs["module_config"] = module_config

        store_exercise(exercise)
        submissions = list(submissions_dict.values())
        store_submissions(submissions)

        kwargs = {}
        if "module_config" in inspect.signature(func).parameters:
            kwargs["module_config"] = module_config

        # Call the actual consumer asynchronously
        background_tasks.add_task(func, exercise, submissions, **kwargs)

        return None

    return wrapper


def submission_selector(
    func: Union[
        Callable[[E, List[S]], S],
        Callable[[E, List[S]], Coroutine[Any, Any, S]],
        Callable[[E, List[S], C], S],
        Callable[[E, List[S], C], Coroutine[Any, Any, S]],
    ],
):
    """
    Receive an exercise and some (not necessarily all!) submissions from the Assessment Module Manager and
    return the submission that should ideally be assessed next.
    If the selector returns None, the LMS will select a random submission in the end.

    This decorator can be used with several types of functions: synchronous or asynchronous, with or without a module config.

    Examples:
        Below are some examples of possible functions that you can decorate with this decorator:

        Without using module config (both synchronous and asynchronous forms):
        >>> @submission_selector
        ... def sync_select_submission(exercise: Exercise, submissions: List[Submission]):
        ...     # process submissions here and return the chosen submission

        >>> @submission_selector
        ... async def async_select_submission(exercise: Exercise, submissions: List[Submission]):
        ...     # process submissions here and return the chosen submission

        With using module config (both synchronous and asynchronous forms):
        >>> @submission_selector
        ... def sync_select_submission_with_config(exercise: Exercise, submissions: List[Submission], module_config: Optional[dict]):
        ...     # process submissions here using module_config and return the chosen submission

        >>> @submission_selector
        ... async def async_select_submission_with_config(exercise: Exercise, submissions: List[Submission], module_config: Optional[dict]):
        ...     # process submissions here using module_config and return the chosen submission
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = (
        inspect.signature(func).parameters["submissions"].annotation.__args__[0]
    )
    module_config_type = (
        inspect.signature(func).parameters["module_config"].annotation
        if "module_config" in inspect.signature(func).parameters
        else Any
    )

    # own request model to allow for `submissionIds` instead of `submission_ids` (camelCase vs snake_case)
    class SubmissionSelectorRequest(BaseModel):
        exercise: exercise_type
        submission_ids: List[int]
        module_config: module_config_type = Depends(get_dynamic_module_config_factory(module_config_type))
        model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @app.post("/select_submission", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
        request: SubmissionSelectorRequest,
        module_config: module_config_type = Depends(
            get_dynamic_module_config_factory(module_config_type)
        ),
    ):
        # The wrapper handles only transmitting submission IDs for efficiency, but the actual selection logic
        # only works with the full submission objects.
        exercise = request.exercise
        submission_ids = request.submission_ids

        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        store_exercise(exercise)

        # Get the full submission objects
        submissions = list(
            get_stored_submissions(submission_type, exercise.id, submission_ids)
        )
        if len(submission_ids) != len(submissions):
            logger.warning(
                "Not all submissions were found in the database! "
                "Have you sent all submissions to the submission consumer before?"
            )
        if not submissions:
            # Nothing to select from
            return -1

        kwargs = {}
        if "module_config" in inspect.signature(func).parameters:
            kwargs["module_config"] = module_config

        # Select the submission
        if inspect.iscoroutinefunction(func):
            submission = await func(exercise, submissions, **kwargs)
        else:
            submission = func(exercise, submissions, **kwargs)

        if submission is None:
            return -1
        return submission.id

    return wrapper


def feedback_consumer(
    func: Union[
        Callable[[E, S, List[F]], None],
        Callable[[E, S, List[F]], Coroutine[Any, Any, None]],
        Callable[[E, S, List[F], C], None],
        Callable[[E, S, List[F], C], Coroutine[Any, Any, None]],
    ],
):
    """
    Receive feedback from the Assessment Module Manager.
    The feedback consumer is usually called whenever the LMS gets feedback from a tutor.

    This decorator can be used with several types of functions: synchronous or asynchronous, with or without a module config.

    Examples:
        Below are some examples of possible functions that you can decorate with this decorator:

        Without using module config (both synchronous and asynchronous forms):
        >>> @feedback_consumer
        ... def sync_process_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
        ...     # process feedback here

        >>> @feedback_consumer
        ... async def async_process_feedback(exercise: Exercise, submission: Submission, feedbacks: List[Feedback]):
        ...     # process feedback here

        With using module config (both synchronous and asynchronous forms):
        >>> @feedback_consumer
        ... def sync_process_feedback_with_config(exercise: Exercise, submission: Submission, feedbacks: List[Feedback], module_config: Optional[dict]):
        ...     # process feedback here using module_config

        >>> @feedback_consumer
        ... async def async_process_feedback_with_config(exercise: Exercise, submission: Submission, feedbacks: List[Feedback], module_config: Optional[dict]):
        ...     # process feedback here using module_config
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submission"].annotation
    feedback_type = (
        inspect.signature(func).parameters["feedbacks"].annotation.__args__[0]
    )
    module_config_type = (
        inspect.signature(func).parameters["module_config"].annotation
        if "module_config" in inspect.signature(func).parameters
        else Any
    )

    @app.post("/feedbacks", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
        background_tasks: BackgroundTasks,
        exercise: exercise_type,
        submission: submission_type,
        feedbacks: List[feedback_type],
        module_config: module_config_type = Depends(
            get_dynamic_module_config_factory(module_config_type)
        ),
    ):

        # Retrieve existing metadata for the exercise, submission and feedback
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        store_exercise(exercise)
        submission.meta.update(get_stored_submission_meta(submission) or {})
        store_submissions([submission])
        for feedback in feedbacks:
            feedback.meta.update(get_stored_feedback_meta(feedback) or {})
            # Change the ID of the LMS to an internal ID
            feedback.id = store_feedback(feedback, is_lms_id=True).id

        kwargs = {}
        if "module_config" in inspect.signature(func).parameters:
            kwargs["module_config"] = module_config

        # Call the actual consumer asynchronously
        background_tasks.add_task(func, exercise, submission, feedbacks, **kwargs)

        return None

    return wrapper


def feedback_provider(
    func: Union[
        Callable[[E, S], List[F]],
        Callable[[E, S], Coroutine[Any, Any, List[F]]],
        Callable[[E, S, C], List[F]],
        Callable[[E, S, C], Coroutine[Any, Any, List[F]]],
        Callable[[E, S, G, C], List[F]],
        Callable[[E, S, G, C], Coroutine[Any, Any, List[F]]],
        Callable[[E, S, G, C, LearnerProfile], List[F]],
        Callable[[E, S, G, C, LearnerProfile], Coroutine[Any, Any, List[F]]],
        # New variants that include latest_submission
        Callable[[E, S, G, C, LearnerProfile, S], List[F]],
        Callable[[E, S, G, C, LearnerProfile, S], Coroutine[Any, Any, List[F]]],
    ],
):
    """
    Provide feedback to the Assessment Module Manager.
    The feedback provider is usually called whenever the tutor requests feedback for a submission in the LMS.

    This decorator can be used with several types of functions: synchronous or asynchronous, with or without a module config.
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submission"].annotation

    # Keep our HEAD behavior for module config (header/default), but allow it to be optional
    module_config_type = (
        inspect.signature(func).parameters["module_config"].annotation
        if "module_config" in inspect.signature(func).parameters
        else Any
    )
    is_graded_type = (
        inspect.signature(func).parameters["is_graded"].annotation
        if "is_graded" in inspect.signature(func).parameters
        else None
    )
    learner_profile_type = (
        inspect.signature(func).parameters["learner_profile"].annotation
        if "learner_profile" in inspect.signature(func).parameters
        else None
    )
    latest_submission_type = (
        inspect.signature(func).parameters["latest_submission"].annotation
        if "latest_submission" in inspect.signature(func).parameters
        else None
    )

    HeaderConfigDep = (
        get_header_module_config_factory(module_config_type)
        if "module_config" in inspect.signature(func).parameters
        else None
    )
    DefaultConfigDep = (
        get_default_module_config_from_app_factory(module_config_type)
        if "module_config" in inspect.signature(func).parameters
        else None
    )

    @app.post("/feedback_suggestions", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
        exercise: exercise_type,
        submission: submission_type,
        isGraded: is_graded_type = Body(True, alias="isGraded"),
        learner_profile: learner_profile_type = Body(None, alias="learnerProfile"),
        latest_submission: latest_submission_type = Body(
            None, alias="latestSubmission"
        ),
        header_cfg: Optional[Any] = (
            Depends(HeaderConfigDep) if HeaderConfigDep else None
        ),
        default_cfg: Optional[Any] = (
            Depends(DefaultConfigDep) if DefaultConfigDep else None
        ),
    ):
        # Resolve module config using our header/default precedence
        config = header_cfg or default_cfg

        # Enrich metadata and persist
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        submission.meta.update(get_stored_submission_meta(submission) or {})
        if latest_submission is not None:
            latest_submission.meta.update(
                get_stored_submission_meta(latest_submission) or {}
            )

        store_exercise(exercise)
        store_submissions([submission])
        if latest_submission is not None:
            store_submissions([latest_submission])

        # Build kwargs for the provider based on what it actually accepts
        kwargs: Dict[str, Any] = {}
        sig = inspect.signature(func).parameters

        if "module_config" in sig:
            kwargs["module_config"] = config
        if "is_graded" in sig:
            kwargs["is_graded"] = isGraded
        if "learner_profile" in sig:
            kwargs["learner_profile"] = learner_profile
        if "latest_submission" in sig:
            kwargs["latest_submission"] = latest_submission

        # Call provider
        if inspect.iscoroutinefunction(func):
            feedbacks = await func(exercise, submission, **kwargs)
        else:
            feedbacks = func(exercise, submission, **kwargs)

        # Store feedback suggestions and assign internal IDs
        feedbacks = store_feedback_suggestions(feedbacks)
        return feedbacks

    return wrapper


def config_schema_provider(cls: Type[C]) -> Type[C]:
    if not issubclass(cls, BaseModel):
        raise TypeError("Decorated class must subclass BaseModel")
    try:
        cls()
    except ValidationError as exc:
        raise TypeError(f"{cls.__name__} needs defaults for all fields") from exc

    def _model_schema() -> Dict[str, Any]:
        try:
            return cls.model_json_schema(by_alias=True)  # v2
        except AttributeError:
            return cls.schema(by_alias=True)  # v1

    def _effective_defaults(app_state) -> Dict[str, Any]:
        cfg = getattr(app_state, "module_config", None)
        if cfg is not None:
            return cfg.dict(by_alias=True)
        try:
            return cls().dict(by_alias=True)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not construct default config: {exc}",
            )

    def _inject_defaults(schema: Dict[str, Any], data: Any) -> None:
        if data is None:
            return
        schema["default"] = data
        t = schema.get("type")
        if t == "object" and isinstance(data, dict):
            for k, sub in (schema.get("properties") or {}).items():
                if k in data:
                    _inject_defaults(sub, data[k])
        elif t == "array" and isinstance(data, list):
            items = schema.get("items")
            if isinstance(items, dict) and data:
                _inject_defaults(items, data[0])

    def _ensure_draft7(schema: Dict[str, Any]) -> None:
        if "$defs" in schema and "definitions" not in schema:
            schema["definitions"] = schema.pop("$defs")

    def _defs(schema: Dict[str, Any]) -> Dict[str, Any]:
        return schema.get("definitions") or schema.get("$defs") or {}

    def _inject_enum(
        schema: Dict[str, Any], def_name: str, prop: str, values: list[str]
    ) -> None:
        if not values:
            return
        d = _defs(schema).get(def_name)
        if not d:
            return
        props = d.get("properties") or {}
        if prop in props:
            prop_schema = props[prop]

            if "anyOf" in prop_schema:
                for any_of_item in prop_schema["anyOf"]:
                    if any_of_item.get("type") == "string":
                        any_of_item["enum"] = values
                        if values:
                            any_of_item["examples"] = [values[0]]
                        break
            else:
                prop_schema["enum"] = values
                if values:
                    prop_schema["examples"] = [values[0]]

    def _inject_model_enums(schema: Dict[str, Any]) -> None:
        try:
            from llm_core.loaders.catalogs import discovered_model_keys

            keys = discovered_model_keys()
            _inject_enum(schema, "AzureModelConfig", "model_name", keys["azure"])
            _inject_enum(schema, "OpenAIModelConfig", "model_name", keys["openai"])
            _inject_enum(schema, "OllamaModelConfig", "model_name", keys["ollama"])
        except ImportError:
            pass

    @app.get("/config_schema")
    async def get_config_schema(request: Request):
        schema = _model_schema()
        _ensure_draft7(schema)
        defaults = _effective_defaults(request.app.state)
        _inject_defaults(schema, defaults)
        _inject_model_enums(schema)
        return schema

    return cls


def evaluation_provider(
    func: Union[
        Callable[[E, S, List[F], List[F]], Any],
        Callable[[E, S, List[F], List[F]], Coroutine[Any, Any, Any]],
    ],
):
    """
    Provide evaluated feedback to the Assessment Module Manager.

    Note: The evaluation provider is usually called during the research and development phase (by the Playground).
    Return arbitrary evaluation results.

    This decorator can be used with several types of functions: synchronous or asynchronous.

    Examples:
        Below are some examples of possible functions that you can decorate with this decorator:

        Without using module config (both synchronous and asynchronous forms):
        >>> @evaluation_provider
        ... def sync_evaluate_feedback(
        ...     exercise: Exercise, submission: Submission,
        ...     true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]
        ... ) -> Any:
        ...     # evaluate predicted feedback here and return evaluation results

        >>> @feedback_provider
        ... async def async_evaluate_feedback(
        ...     exercise: Exercise, submission: Submission,
        ...     true_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]
        ... ) -> Any:
        ...     # evaluate predicted feedback here and return evaluation results
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submission"].annotation
    feedback_type = (
        inspect.signature(func).parameters["predicted_feedbacks"].annotation.__args__[0]
    )

    @app.post("/evaluation", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
        exercise: exercise_type,
        submission: submission_type,
        true_feedbacks: List[feedback_type],
        predicted_feedbacks: List[feedback_type],
    ):
        # Retrieve existing metadata for the exercise, submission and feedback
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        submission.meta.update(get_stored_submission_meta(submission) or {})
        for feedback in true_feedbacks + predicted_feedbacks:
            feedback.meta.update(get_stored_feedback_meta(feedback) or {})

        # Call the actual provider
        if inspect.iscoroutinefunction(func):
            evaluation = await func(
                exercise, submission, true_feedbacks, predicted_feedbacks
            )
        else:
            evaluation = func(exercise, submission, true_feedbacks, predicted_feedbacks)

        return evaluation

    return wrapper