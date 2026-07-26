from unittest.mock import patch

from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.exercise_with_submissions_dto import (
    ExerciseMode,
    ExerciseType,
    ExerciseWithSubmissionsDTO,
)
from iris.domain.data.lecture_dto import PyrisLectureDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.run_state_dto import RunStateEnum
from iris.domain.status.suggested_context_dto import SuggestedContextDTO
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.tools.switch_chat_context import create_tool_switch_chat_context
from iris.web.status.status_update import ChatRunCallback


class _RecordedSwitch:
    def __init__(self):
        self.value = "unset"

    def __call__(self, suggested_context):
        self.value = suggested_context


def _exercise(exercise_id: int, exercise_type: ExerciseType, title: str):
    return ExerciseWithSubmissionsDTO(
        id=exercise_id,
        title=title,
        type=exercise_type,
        mode=ExerciseMode.INDIVIDUAL,
    )


def _dto(
    chat_mode: IrisChatMode = IrisChatMode.COURSE,
    programming_exercise: ProgrammingExerciseDTO | None = None,
    lecture: PyrisLectureDTO | None = None,
    lectures: list[PyrisLectureDTO] | None = None,
) -> ChatPipelineExecutionDTO:
    return ChatPipelineExecutionDTO(
        settings=None,
        chat_mode=chat_mode,
        user=UserDTO(id=7),
        course=CourseDTO(
            id=99,
            name="Test Course",
            exercises=[
                _exercise(11, ExerciseType.PROGRAMMING, "Sorting"),
                _exercise(12, ExerciseType.TEXT, "Essay"),
                _exercise(13, ExerciseType.QUIZ, "Quiz 1"),
            ],
            lectures=lectures or [],
        ),
        programming_exercise=programming_exercise,
        lecture=lecture,
    )


def _lectures() -> list[PyrisLectureDTO]:
    """The course lectures as Artemis sends them in the course DTO."""
    return [
        PyrisLectureDTO(id=41, title="Sorting Algorithms"),
        PyrisLectureDTO(id=42, title="Hashing"),
    ]


def test_switch_to_programming_exercise_records_switch():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("PROGRAMMING_EXERCISE_CHAT", 11)

    assert "Successfully registered" in result
    assert recorded.value == SuggestedContextDTO(
        mode=IrisChatMode.EXERCISE, entity_id=11
    )


def test_switch_corrects_mixed_up_exercise_mode():
    """The exercise type on the DTO wins over the mode the agent passed."""
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("PROGRAMMING_EXERCISE_CHAT", 12)

    assert "Successfully registered" in result
    assert recorded.value == SuggestedContextDTO(
        mode=IrisChatMode.TEXT_EXERCISE, entity_id=12
    )


def test_switch_to_unknown_exercise_is_rejected():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("PROGRAMMING_EXERCISE_CHAT", 999)

    assert "no exercise with ID 999" in result
    assert recorded.value == "unset"


def test_switch_to_unsupported_exercise_type_is_rejected():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("PROGRAMMING_EXERCISE_CHAT", 13)

    assert "Only programming and text exercises" in result
    assert recorded.value == "unset"


def test_switch_with_unknown_mode_is_rejected():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("EXAM_CHAT", 11)

    assert "unknown mode" in result
    assert recorded.value == "unset"


def test_switch_to_course_uses_course_id():
    """There is exactly one course target, so a wrong entity id is corrected."""
    exercise_dto = _dto(
        chat_mode=IrisChatMode.EXERCISE,
        programming_exercise=ProgrammingExerciseDTO(id=11, name="Sorting"),
    )
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(exercise_dto, recorded)

    result = tool("COURSE_CHAT", 12345)

    assert "Successfully registered" in result
    assert recorded.value == SuggestedContextDTO(mode=IrisChatMode.COURSE, entity_id=99)


def test_switch_to_active_context_clears_pending_switch():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("COURSE_CHAT", 99)

    assert "already active" in result
    assert recorded.value is None


def test_switch_from_lecture_a_to_lecture_b_records_switch():
    """The A to B flow the lecture list tool exists for."""
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        ),
        recorded,
    )

    result = tool("LECTURE_CHAT", 42)

    assert "Successfully registered" in result
    assert recorded.value == SuggestedContextDTO(
        mode=IrisChatMode.LECTURE, entity_id=42
    )


def test_switch_to_unknown_lecture_is_rejected():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(lectures=_lectures()), recorded)

    result = tool("LECTURE_CHAT", 999)

    assert "no lecture with ID 999" in result
    assert recorded.value == "unset"


def test_switch_to_active_lecture_clears_pending_switch():
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        ),
        recorded,
    )

    result = tool("LECTURE_CHAT", 41)

    assert "already active" in result
    assert recorded.value is None


def test_switch_to_lecture_is_accepted_when_lecture_list_is_empty():
    """An empty list means Artemis sent no lectures field, so Artemis decides."""
    recorded = _RecordedSwitch()
    tool = create_tool_switch_chat_context(_dto(), recorded)

    result = tool("LECTURE_CHAT", 42)

    assert "Successfully registered" in result
    assert recorded.value == SuggestedContextDTO(
        mode=IrisChatMode.LECTURE, entity_id=42
    )


def test_send_result_carries_suggested_context_on_the_wire():
    callback = ChatRunCallback("run-1", "https://artemis.example", None)
    suggested = SuggestedContextDTO(mode=IrisChatMode.EXERCISE, entity_id=11)

    with patch.object(
        ChatRunCallback, "_send_status_payload", return_value=True
    ) as send:
        assert callback.send_result("answer", tokens=[], suggested_context=suggested)

    payload = send.call_args.args[0]
    assert payload["suggestedContext"] == {
        "mode": "PROGRAMMING_EXERCISE_CHAT",
        "entityId": 11,
    }


def test_send_result_without_switch_omits_suggested_context():
    callback = ChatRunCallback("run-1", "https://artemis.example", None)

    with patch.object(
        ChatRunCallback, "_send_status_payload", return_value=True
    ) as send:
        assert callback.send_result("answer", tokens=[], suggested_context=None)

    payload = send.call_args.args[0]
    assert payload["suggestedContext"] is None


def test_chat_status_update_dto_parses_suggested_context_alias():
    dto = ChatStatusUpdateDTO(
        run_state=RunStateEnum.RUNNING,
        suggestedContext={"mode": "LECTURE_CHAT", "entityId": 5},
    )
    assert dto.suggested_context == SuggestedContextDTO(
        mode=IrisChatMode.LECTURE, entity_id=5
    )
