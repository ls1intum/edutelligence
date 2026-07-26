"""Tool that lets the agent switch the active chat context.

The tool does not change anything inside the running pipeline. It records the
requested target on the execution state; the chat pipeline attaches it to the
final result status update, and Artemis validates and applies the switch
(persisting a CTXSWAP marker and updating the session's mode and entity id).
"""

from typing import Callable, Optional

from iris.common.logging_config import get_logger
from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.data.exercise_with_submissions_dto import ExerciseType
from iris.domain.status.suggested_context_dto import SuggestedContextDTO
from iris.pipeline.chat.iris_chat_mode import IrisChatMode

logger = get_logger(__name__)

_EXERCISE_TYPE_TO_MODE: dict[ExerciseType, IrisChatMode] = {
    ExerciseType.PROGRAMMING: IrisChatMode.EXERCISE,
    ExerciseType.TEXT: IrisChatMode.TEXT_EXERCISE,
}

_EXERCISE_MODES = {IrisChatMode.EXERCISE, IrisChatMode.TEXT_EXERCISE}


def _current_entity_id(dto: ChatPipelineExecutionDTO) -> Optional[int]:
    """Return the entity id of the currently active context."""
    match dto.chat_mode:
        case IrisChatMode.COURSE:
            return dto.course.id
        case IrisChatMode.LECTURE:
            return dto.lecture.id if dto.lecture else None
        case IrisChatMode.EXERCISE:
            return dto.programming_exercise.id if dto.programming_exercise else None
        case IrisChatMode.TEXT_EXERCISE:
            return dto.text_exercise.id if dto.text_exercise else None
    return None


def create_tool_switch_chat_context(
    dto: ChatPipelineExecutionDTO,
    record_switch: Callable[[Optional[SuggestedContextDTO]], None],
) -> Callable[[str, int], str]:
    """
    Create a tool that switches the active chat context.

    Args:
        dto: The chat pipeline execution DTO (used to validate targets and
            to detect switches to the already active context).
        record_switch: Callback that stores the validated switch request on
            the pipeline execution state (last call wins).

    Returns:
        Callable[[str, int], str]: Function the agent calls to switch context.
    """

    def switch_chat_context(mode: str, entity_id: int) -> str:
        """
        Switch the active context of this chat to a different exercise, lecture,
        or back to the course itself.
        You MUST call this tool BEFORE answering whenever the student asks about
        an exercise or lecture that is NOT the currently active context, and
        whenever the student asks a general course-level question while an
        exercise or lecture context is active (switch to "COURSE_CHAT" then).
        Find the target's ID first, via the exercise list tool for exercises
        or the lecture list tool for lectures, and never guess IDs.
        The switch is applied together with your final answer, so after calling
        this tool simply continue and answer the student's question about the
        new context.

        Args:
            mode: The target context type. One of "PROGRAMMING_EXERCISE_CHAT",
                "TEXT_EXERCISE_CHAT", "LECTURE_CHAT", or "COURSE_CHAT".
            entity_id: The ID of the target entity: the exercise ID for exercise
                modes, the lecture ID for "LECTURE_CHAT", or the course ID for
                "COURSE_CHAT".

        Returns:
            str: Whether the switch was registered, or why it was rejected.
        """
        try:
            target_mode = IrisChatMode(mode)
        except ValueError:
            valid = ", ".join(m.value for m in IrisChatMode)
            return f"Error: unknown mode '{mode}'. Valid modes are: {valid}."

        if target_mode == IrisChatMode.COURSE:
            # There is exactly one valid course target, so the course id is
            # used regardless of the passed entity_id.
            entity_id = dto.course.id

        if target_mode in _EXERCISE_MODES:
            exercise = next(
                (ex for ex in dto.course.exercises or [] if ex.id == entity_id),
                None,
            )
            if exercise is None:
                return (
                    f"Error: no exercise with ID {entity_id} exists in this course. "
                    "Use the exercise list tool to find the correct exercise ID."
                )
            actual_mode = _EXERCISE_TYPE_TO_MODE.get(exercise.type)
            if actual_mode is None:
                return (
                    f"Error: exercise '{exercise.title}' has type "
                    f"'{exercise.type.value}'. Only programming and text "
                    "exercises support context switching."
                )
            # The exercise type on the DTO is authoritative; silently correct a
            # mixed-up programming/text mode instead of failing the switch.
            target_mode = actual_mode

        if target_mode == IrisChatMode.LECTURE:
            lectures = dto.course.lectures
            # An empty list means Artemis did not send a lectures field, most
            # likely because the instance is not updated yet. Absence of data is
            # no proof of nonexistence, so the validation is left to Artemis
            # rather than blocking a switch the agent may well have gotten right.
            if lectures and all(lecture.id != entity_id for lecture in lectures):
                return (
                    f"Error: no lecture with ID {entity_id} exists in this course. "
                    "Use the lecture list tool to find the correct lecture ID."
                )

        if target_mode == dto.chat_mode and entity_id == _current_entity_id(dto):
            record_switch(None)
            return (
                "This context is already active. Answer the student's question "
                "without switching."
            )

        record_switch(SuggestedContextDTO(mode=target_mode, entity_id=entity_id))
        logger.info(
            "Agent requested context switch | mode=%s entity_id=%d",
            target_mode.value,
            entity_id,
        )
        return (
            f"Successfully registered the switch to context '{target_mode.value}' "
            f"with ID {entity_id}. It is applied together with your final answer. "
            "Now answer the student's question in the new context."
        )

    return switch_chat_context
