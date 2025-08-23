# type: ignore # too much weird behavior of mypy with decorators
import inspect
from fastapi import Depends, BackgroundTasks, Body
from pydantic import ConfigDict, BaseModel, ValidationError
from pydantic.alias_generators import to_camel
from typing import TypeVar, Callable, List, Union, Any, Coroutine, Type, Optional

from athena.app import app
from athena.authenticate import authenticated
from athena.metadata import with_meta
from athena.module_config import get_dynamic_module_config_factory
from athena.logger import logger
from athena.schemas import Exercise, Submission, Feedback, LearnerProfile
from athena.storage import get_stored_submission_meta, get_stored_exercise_meta, get_stored_feedback_meta, \
    store_exercise, store_feedback, store_feedback_suggestions, store_submissions, get_stored_submissions

E = TypeVar('E', bound=Exercise)
S = TypeVar('S', bound=Submission)
F = TypeVar('F', bound=Feedback)
G = TypeVar('G', bound=bool)

# Config type
C = TypeVar("C", bound=BaseModel)

module_responses = {
    403: {
        "description": "API secret is invalid - set the environment variable SECRET and the Authorization header "
                       "to the same value",
    }
}


def submissions_consumer(func: Union[
    Callable[[E, List[S]], None],
    Callable[[E, List[S]], Coroutine[Any, Any, None]],
    Callable[[E, List[S], C], None],
    Callable[[E, List[S], C], Coroutine[Any, Any, None]]
]):
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
    submission_type = inspect.signature(func).parameters["submissions"].annotation.__args__[0]
    module_config_type = inspect.signature(func).parameters["module_config"].annotation if "module_config" in inspect.signature(func).parameters else None

    @app.post("/submissions", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
            background_tasks: BackgroundTasks,
            exercise: exercise_type,
            submissions: List[submission_type],
            module_config: module_config_type = Depends(get_dynamic_module_config_factory(module_config_type))):

        # Retrieve existing metadata for the exercise and submissions
        exercise_meta = get_stored_exercise_meta(exercise) or {}
        exercise_meta.update(exercise.meta)
        exercise.meta = exercise_meta
        submissions_dict = {s.id: s for s in submissions}
        if submissions:
            stored_submissions = get_stored_submissions(
                submissions[0].__class__, exercise.id, [s.id for s in submissions])
            for stored_submission in stored_submissions:
                if stored_submission.id in submissions_dict:
                    submission_meta = get_stored_submission_meta(stored_submission) or {}
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


def submission_selector(func: Union[
    Callable[[E, List[S]], S],
    Callable[[E, List[S]], Coroutine[Any, Any, S]],
    Callable[[E, List[S], C], S],
    Callable[[E, List[S], C], Coroutine[Any, Any, S]]
]):
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
    submission_type = inspect.signature(func).parameters["submissions"].annotation.__args__[0]
    module_config_type = inspect.signature(func).parameters["module_config"].annotation if "module_config" in inspect.signature(func).parameters else None

    # own request model to allow for `submissionIds` instead of `submission_ids` (camelCase vs snake_case)
    class SubmissionSelectorRequest(BaseModel):
        exercise: exercise_type
        submission_ids: List[int]
        module_config: module_config_type = Depends(get_dynamic_module_config_factory(module_config_type))
        model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @app.post("/select_submission", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(request: SubmissionSelectorRequest):
        # The wrapper handles only transmitting submission IDs for efficiency, but the actual selection logic
        # only works with the full submission objects.
        exercise = request.exercise
        submission_ids = request.submission_ids
        module_config = request.module_config

        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        store_exercise(exercise)

        # Get the full submission objects
        submissions = list(get_stored_submissions(submission_type, exercise.id, submission_ids))
        if len(submission_ids) != len(submissions):
            logger.warning("Not all submissions were found in the database! "
                           "Have you sent all submissions to the submission consumer before?")
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


def feedback_consumer(func: Union[
    Callable[[E, S, List[F]], None],
    Callable[[E, S, List[F]], Coroutine[Any, Any, None]],
    Callable[[E, S, List[F], C], None],
    Callable[[E, S, List[F], C], Coroutine[Any, Any, None]]
]):
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
    feedback_type = inspect.signature(func).parameters["feedbacks"].annotation.__args__[0]
    module_config_type = inspect.signature(func).parameters["module_config"].annotation if "module_config" in inspect.signature(func).parameters else None

    @app.post("/feedbacks", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
            background_tasks: BackgroundTasks,
            exercise: exercise_type,
            submission: submission_type,
            feedbacks: List[feedback_type],
            module_config: module_config_type = Depends(get_dynamic_module_config_factory(module_config_type))):

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


def feedback_provider(func: Union[
    Callable[[E, S], List[F]],
    Callable[[E, S], Coroutine[Any, Any, List[F]]],
    Callable[[E, S, C], List[F]],
    Callable[[E, S, C], Coroutine[Any, Any, List[F]]],
    Callable[[E, S, G, C], List[F]],
    Callable[[E, S, G, C], Coroutine[Any, Any, List[F]]],
    Callable[[E, S, G, C, LearnerProfile], List[F]],
    Callable[[E, S, G, C, LearnerProfile], Coroutine[Any, Any, List[F]]],
    Callable[[E, S, G, C, LearnerProfile, S], List[F]],
    Callable[[E, S, G, C, LearnerProfile, S], Coroutine[Any, Any, List[F]]],
]):
    """
    Provide feedback to the Assessment Module Manager.
    The feedback provider is usually called whenever the tutor requests feedback for a submission in the LMS.

    This decorator can be used with several types of functions: synchronous or asynchronous, with or without a module config.

    Examples:
        Below are some examples of possible functions that you can decorate with this decorator:

        Without using module config (both synchronous and asynchronous forms):
        >>> @feedback_provider
        ... def sync_suggest_feedback(exercise: Exercise, submission: Submission):
        ...     # suggest feedback here and return it as a list

        >>> @feedback_provider
        ... async def async_suggest_feedback(exercise: Exercise, submission: Submission):
        ...     # suggest feedback here and return it as a list

        With using module config (both synchronous and asynchronous forms):
        >>> @feedback_provider
        ... def sync_suggest_feedback_with_config(exercise: Exercise, submission: Submission, module_config: Optional[dict]):
        ...     # suggest feedback here using module_config and return it as a list

        >>> @feedback_provider
        ... async def async_suggest_feedback_with_config(exercise: Exercise, submission: Submission, module_config: Optional[dict]):
        ...     # suggest feedback here using module_config and return it as a list

        With learner profile (both synchronous and asynchronous forms):
        >>> @feedback_provider
        ... def sync_suggest_feedback_with_profile(exercise: Exercise, submission: Submission, module_config: Optional[dict], learner_profile: Optional[LearnerProfile]):
        ...     # suggest feedback here using module_config and learner_profile and return it as a list

        >>> @feedback_provider
        ... async def async_suggest_feedback_with_profile(exercise: Exercise, submission: Submission, module_config: Optional[dict], learner_profile: Optional[LearnerProfile]):
        ...     # suggest feedback here using module_config and learner_profile and return it as a list

        With previous submission (both synchronous and asynchronous forms):
        >>> @feedback_provider
        ... def sync_suggest_feedback_with_profile(exercise: Exercise, submission: Submission, module_config: Optional[dict], learner_profile: Optional[LearnerProfile], latest_submission: Optional[Submission]):
        ...     # suggest feedback here using module_config and learner_profile and return it as a list

        >>> @feedback_provider
        ... async def async_suggest_feedback_with_profile(exercise: Exercise, submission: Submission, module_config: Optional[dict], learner_profile: Optional[LearnerProfile], latest_submission: Optional[Submission]):
        ...     # suggest feedback here using module_config and learner_profile and return it as a list
    """
    exercise_type = inspect.signature(func).parameters["exercise"].annotation
    submission_type = inspect.signature(func).parameters["submission"].annotation
    module_config_type = inspect.signature(func).parameters["module_config"].annotation if "module_config" in inspect.signature(func).parameters else None
    is_graded_type = inspect.signature(func).parameters["is_graded"].annotation if "is_graded" in inspect.signature(func).parameters else None
    learner_profile_type = inspect.signature(func).parameters["learner_profile"].annotation if "learner_profile" in inspect.signature(func).parameters else None
    latest_submission_type = inspect.signature(func).parameters["latest_submission"].annotation if "latest_submission" in inspect.signature(func).parameters else None

    @app.post("/feedback_suggestions", responses=module_responses)
    @authenticated
    @with_meta
    async def wrapper(
            exercise: exercise_type,
            submission: submission_type,
            isGraded: is_graded_type = Body(True, alias="isGraded"),
            learner_profile: learner_profile_type = Body(None, alias="learnerProfile"),
            latest_submission: latest_submission_type = Body(None, alias="latestSubmission"),
            module_config: module_config_type = Depends(get_dynamic_module_config_factory(module_config_type))):

        # Retrieve existing metadata for the exercise, submission and feedback
        exercise.meta.update(get_stored_exercise_meta(exercise) or {})
        submission.meta.update(get_stored_submission_meta(submission) or {})

        store_exercise(exercise)
        store_submissions([submission])

        # Build kwargs for the function
        kwargs = {}
        if "module_config" in inspect.signature(func).parameters:
            kwargs["module_config"] = module_config

        if "is_graded" in inspect.signature(func).parameters:
            kwargs["is_graded"] = isGraded

        if "learner_profile" in inspect.signature(func).parameters:
            kwargs["learner_profile"] = learner_profile

        if "latest_submission" in inspect.signature(func).parameters:
            kwargs["latest_submission"] = latest_submission

        # Filter out unexpected kwargs and log warnings
        accepted_params = set(inspect.signature(func).parameters.keys())
        all_possible_kwargs = {
            "module_config": module_config,
            "is_graded": isGraded,
            "learner_profile": learner_profile,
            "latest_submission": latest_submission,
        }

        # Only pass accepted kwargs
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in accepted_params}

        # Log warning for any extra provided (not supported by the module)
        for k, v in all_possible_kwargs.items():
            if k not in accepted_params and v is not None:
                logger.warning("%s: Received unexpected argument '%s' (value: %s), but this module does not support it. Ignoring.", func.__name__, k, v)

        # Call the actual provider
        if inspect.iscoroutinefunction(func):
            feedbacks = await func(exercise, submission, **filtered_kwargs)
        else:
            feedbacks = func(exercise, submission, **filtered_kwargs)

        # Store feedback suggestions and assign internal IDs
        feedbacks = store_feedback_suggestions(feedbacks)
        return feedbacks
    return wrapper


def config_schema_provider(cls: Type[C]) -> Type[C]:
    """
    Decorator for a class to provide an endpoint that returns the configuration class schema.

    The decorated class must be a subclass of BaseModel and must have default values for all parameters (default configuration).

    Example:
        >>> @config_schema_provider
        ... class MyConfig(BaseModel):
        ...     my_parameter: str = "default value"
    """
    if not issubclass(cls, BaseModel):
        raise TypeError("Decorated class must be a subclass of BaseModel")

    # Try to initialize the class without parameters (default values will be used)
    try:
        cls()
    except ValidationError as exc:
        raise TypeError(f'Cannot initialize {cls.__name__} without parameters, please provide default values for all parameters') from exc

    @app.get("/config_schema")
    async def wrapper():
        return cls.model_json_schema()

    return cls


def evaluation_provider(func: Union[
    Callable[[E, S, List[F], List[F]], Any],
    Callable[[E, S, List[F], List[F]], Coroutine[Any, Any, Any]]
]):
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
    feedback_type = inspect.signature(func).parameters["predicted_feedbacks"].annotation.__args__[0]

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
            evaluation = await func(exercise, submission, true_feedbacks, predicted_feedbacks)
        else:
            evaluation = func(exercise, submission, true_feedbacks, predicted_feedbacks)

        return evaluation
    return wrapper
