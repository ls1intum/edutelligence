import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.exercise_with_submissions_dto import (
    ExerciseMode,
    ExerciseType,
    ExerciseWithSubmissionsDTO,
)
from iris.domain.data.lecture_dto import PyrisLectureDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.retrieval.lecture.lecture_retrieval_dto import LectureRetrievalDTO
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.run_state_dto import RunStateEnum
from iris.domain.status.suggested_context_dto import SuggestedContextDTO
from iris.pipeline.abstract_agent_pipeline import AgentPipelineExecutionState
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.pipeline.shared.utils import generate_structured_tool_from_function
from iris.tools.chat_tool_providers import (
    provide_additional_exercise_details,
    provide_build_logs_analysis,
    provide_exercise_problem_statement,
    provide_feedbacks,
    provide_file_lookup,
    provide_lecture_list,
    provide_lecture_retrieval,
    provide_mcq_generation,
    provide_repository_files,
    provide_submission_details,
    provide_switch_chat_context,
)
from iris.tools.switch_chat_context import create_tool_switch_chat_context
from iris.web.status.status_update import ChatRunCallback
from tests.test_mcq_prompt_rendering import (
    _minimal_course_chat_context,
    _minimal_lecture_chat_context,
    _render_template,
)


class _RecordedSwitch:
    def __init__(self):
        self.value = "unset"

    def __call__(self, suggested_context):
        self.value = suggested_context


class _RecordingLectureRetriever:
    """Stands in for LectureRetrieval and records the scope it receives."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[],
            lecture_unit_page_chunks=[],
        )


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
    lecture_unit_id: int | None = None,
    submission: ProgrammingSubmissionDTO | None = None,
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
        lectureUnitId=lecture_unit_id,
        programmingExerciseSubmission=submission,
    )


def _lecture_chat_state(dto: ChatPipelineExecutionDTO) -> AgentPipelineExecutionState:
    """A pipeline state carrying only what the two lecture providers read."""
    state = AgentPipelineExecutionState()
    state.dto = dto
    state.callback = None
    state.query_text = "How does hashing work?"
    state.message_history = []
    state.lecture_content_storage = {}
    state.allow_lecture_tool = True
    state.pending_context_switch = None
    # Set upfront so the provider reuses it instead of building a real retriever.
    state.lecture_retriever = _RecordingLectureRetriever()
    return state


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


def test_retrieval_follows_the_switch_from_lecture_a_to_lecture_b():
    """The full A to B flow: after the switch the agent answers from lecture B.

    Recording the switch alone leaves the student without an answer, so this
    drives the retrieval tool the pipeline hands the agent and checks the scope
    it queries.
    """
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
            lecture_unit_id=410,
        )
    )

    switch = provide_switch_chat_context(state)
    assert "Successfully registered" in switch("LECTURE_CHAT", 42)

    provide_lecture_retrieval(state)()

    call = state.lecture_retriever.calls[-1]
    assert call["lecture_id"] == 42
    assert call["lecture_unit_id"] is None
    assert call["course_id"] == 99


def test_retrieval_stays_on_the_active_lecture_without_a_switch():
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
            lecture_unit_id=410,
        )
    )

    provide_lecture_retrieval(state)()

    call = state.lecture_retriever.calls[-1]
    assert call["lecture_id"] == 41
    assert call["lecture_unit_id"] == 410


def _exercise_chat_state() -> AgentPipelineExecutionState:
    """A programming exercise chat on exercise 11 (Sorting) with a submission."""
    state = AgentPipelineExecutionState()
    state.dto = _dto(
        chat_mode=IrisChatMode.EXERCISE,
        programming_exercise=ProgrammingExerciseDTO(id=11, title="Sorting"),
        submission=ProgrammingSubmissionDTO(
            id=5,
            repository={"src/Sort.java": "class Sort {}"},
            isPractice=False,
            buildFailed=False,
        ),
    )
    state.callback = None
    state.lecture_content_storage = {}
    state.pending_context_switch = None
    return state


_EXERCISE_TOOL_CALLS = [
    pytest.param(provide_submission_details, (), id="submission_details"),
    pytest.param(
        provide_additional_exercise_details, (), id="additional_exercise_details"
    ),
    pytest.param(provide_build_logs_analysis, (), id="build_logs_analysis"),
    pytest.param(provide_feedbacks, (), id="feedbacks"),
    pytest.param(provide_repository_files, (), id="repository_files"),
    pytest.param(provide_file_lookup, ("src/Sort.java",), id="file_lookup"),
]


@pytest.mark.parametrize("provider,args", _EXERCISE_TOOL_CALLS)
def test_exercise_tools_refuse_after_the_switch_from_exercise_a_to_exercise_b(
    provider, args
):
    """After A to B the exercise tools must not hand out A's data as B's."""
    state = _exercise_chat_state()
    tool = provider(state)

    switch = provide_switch_chat_context(state)
    assert "Successfully registered" in switch("TEXT_EXERCISE_CHAT", 12)

    result = tool(*args)

    assert isinstance(result, str)
    assert result.startswith("Unavailable")
    assert "'Sorting'" in result


@pytest.mark.parametrize("provider,args", _EXERCISE_TOOL_CALLS)
def test_exercise_tools_return_their_data_without_a_switch(provider, args):
    state = _exercise_chat_state()

    result = provider(state)(*args)

    assert not (isinstance(result, str) and result.startswith("Unavailable"))


def test_exercise_tools_keep_their_data_when_the_switch_targets_the_active_exercise():
    state = _exercise_chat_state()
    tool = provide_file_lookup(state)

    provide_switch_chat_context(state)("PROGRAMMING_EXERCISE_CHAT", 11)

    assert tool("src/Sort.java").startswith("src/Sort.java:")


def test_guarded_exercise_tool_keeps_its_name_and_arguments():
    """The agent sees the guarded tool exactly like the unguarded one."""
    structured = generate_structured_tool_from_function(
        provide_file_lookup(_exercise_chat_state())
    )

    assert structured.name == "file_lookup"
    assert list(structured.args) == ["file_path"]


def _course_chat_state() -> AgentPipelineExecutionState:
    state = AgentPipelineExecutionState()
    state.dto = _dto()
    state.callback = None
    state.lecture_content_storage = {}
    state.pending_context_switch = None
    return state


def test_problem_statement_of_another_exercise_reminds_the_agent_to_switch():
    """Reading another exercise's statement is the step the agent answers right after."""
    result = provide_exercise_problem_statement(_course_chat_state())(11)

    assert "call `switch_chat_context`" in result
    assert 'mode "PROGRAMMING_EXERCISE_CHAT" and entity_id 11' in result


def test_problem_statement_reminder_uses_the_text_exercise_mode():
    result = provide_exercise_problem_statement(_course_chat_state())(12)

    assert 'mode "TEXT_EXERCISE_CHAT" and entity_id 12' in result


def test_problem_statement_of_the_active_exercise_carries_no_reminder():
    result = provide_exercise_problem_statement(_exercise_chat_state())(11)

    assert "switch_chat_context" not in result


def test_problem_statement_carries_no_reminder_after_the_switch_to_that_exercise():
    state = _course_chat_state()
    tool = provide_exercise_problem_statement(state)

    provide_switch_chat_context(state)("PROGRAMMING_EXERCISE_CHAT", 11)

    assert "switch_chat_context" not in tool(11)


def test_problem_statement_reminds_again_when_the_switch_targets_another_exercise():
    state = _course_chat_state()
    tool = provide_exercise_problem_statement(state)

    provide_switch_chat_context(state)("TEXT_EXERCISE_CHAT", 12)

    assert "entity_id 11" in tool(11)


def test_problem_statement_of_unswitchable_or_unknown_exercises_carries_no_reminder():
    tool = provide_exercise_problem_statement(_course_chat_state())

    assert "switch_chat_context" not in tool(13)
    assert tool(999) == "Exercise not found"


def test_problem_statement_tool_keeps_its_name_and_arguments():
    structured = generate_structured_tool_from_function(
        provide_exercise_problem_statement(_course_chat_state())
    )

    assert structured.name == "get_exercise_problem_statement"
    assert list(structured.args) == ["exercise_id"]


def test_course_chat_prompt_does_not_claim_retrieval_is_scoped_to_a_lecture():
    """In a course chat retrieval is course-wide, so it can answer without a switch."""
    rendered = _render_template("chat_system_prompt.j2", _minimal_course_chat_context())

    assert "scoped to the active lecture" not in rendered
    assert "searches all lectures of the course" in rendered


def test_lecture_chat_prompt_states_retrieval_is_scoped_to_the_active_lecture():
    rendered = _render_template(
        "chat_system_prompt.j2", _minimal_lecture_chat_context()
    )

    assert "scoped to the active lecture" in rendered
    assert "searches all lectures of the course" not in rendered


def test_mcq_generation_follows_the_switch_from_lecture_a_to_lecture_b():
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        )
    )
    state.mcq_pipeline = None
    state.db = None

    with (
        patch(
            "iris.tools.chat_tool_providers.create_tool_generate_mcq_questions"
        ) as create_tool,
        patch(
            "iris.tools.chat_tool_providers.retrieve_lecture_content_for_mcq",
            return_value=("content", []),
        ) as retrieve,
    ):
        provide_mcq_generation(state)
        supplier = create_tool.call_args.kwargs["lecture_content_supplier"]

        supplier()
        assert retrieve.call_args.kwargs["lecture_id"] == 41

        provide_switch_chat_context(state)("LECTURE_CHAT", 42)
        supplier()
        assert retrieve.call_args.kwargs["lecture_id"] == 42


def test_switch_clears_lecture_content_of_the_previous_context():
    """Content of lecture A must not end up as a citation in the answer about B."""
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        )
    )
    state.lecture_content_storage["content"] = object()

    provide_switch_chat_context(state)("LECTURE_CHAT", 42)

    assert "content" not in state.lecture_content_storage


def test_cancelling_a_switch_clears_the_content_of_the_cancelled_target():
    """A to B to A: content retrieved for B must not be cited in the answer about A."""
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
            lecture_unit_id=410,
        )
    )
    switch = provide_switch_chat_context(state)
    retrieval = provide_lecture_retrieval(state)

    switch("LECTURE_CHAT", 42)
    retrieval()
    assert state.lecture_retriever.calls[-1]["lecture_id"] == 42
    assert "content" in state.lecture_content_storage

    assert "already active" in switch("LECTURE_CHAT", 41)

    assert state.pending_context_switch is None
    assert "content" not in state.lecture_content_storage
    retrieval()
    assert state.lecture_retriever.calls[-1]["lecture_id"] == 41


def test_repeating_the_same_switch_keeps_the_content_of_its_target():
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        )
    )
    switch = provide_switch_chat_context(state)
    switch("LECTURE_CHAT", 42)
    content = object()
    state.lecture_content_storage["content"] = content

    switch("LECTURE_CHAT", 42)

    assert state.lecture_content_storage["content"] is content


def _citation_run(pending_context_switch):
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.citation_pipeline = MagicMock(return_value="cited answer")
    pipeline.citation_pipeline.tokens = []
    current_view = LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[],
    )
    state = SimpleNamespace(
        dto=SimpleNamespace(settings=None, user=SimpleNamespace(lang_key="en")),
        variant=SimpleNamespace(id="default"),
        faq_storage={},
        lecture_content_storage={"current_view": current_view},
        pending_context_switch=pending_context_switch,
    )
    pipeline._add_citations(state, "answer")  # pylint: disable=protected-access
    return pipeline.citation_pipeline, current_view


def test_citations_use_the_current_view_without_a_switch():
    citation_pipeline, current_view = _citation_run(None)

    assert citation_pipeline.call_args.args[0] is current_view


def test_citations_skip_the_current_view_of_the_original_context_after_a_switch():
    citation_pipeline, _ = _citation_run(
        SuggestedContextDTO(mode=IrisChatMode.LECTURE, entity_id=42)
    )

    citation_pipeline.assert_not_called()


def test_switch_to_the_active_context_keeps_its_lecture_content():
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        )
    )
    current_view = object()
    state.lecture_content_storage["current_view"] = current_view

    provide_switch_chat_context(state)("LECTURE_CHAT", 41)

    assert state.lecture_content_storage["current_view"] is current_view


def test_lecture_list_reaches_the_agent_without_indexed_lecture_content():
    """A course with lectures but no ingested content still allows a switch.

    Indexed lecture content gates retrieval, not discovery. Gating the list as
    well would leave the agent without a target ID, and the prompt forbids
    guessing one, so the lecture switch would never happen in such a course.
    """
    state = _lecture_chat_state(_dto(lectures=_lectures()))
    state.allow_lecture_tool = False

    lecture_list = provide_lecture_list(state)

    assert lecture_list is not None
    assert [entry["lecture_id"] for entry in lecture_list()] == [41, 42]

    switch = provide_switch_chat_context(state)
    assert "Successfully registered" in switch("LECTURE_CHAT", 42)
    assert state.pending_context_switch == SuggestedContextDTO(
        mode=IrisChatMode.LECTURE, entity_id=42
    )


def test_lecture_retrieval_stays_gated_on_indexed_lecture_content():
    """Retrieval reads the vector database, so it keeps the index precondition."""
    state = _lecture_chat_state(_dto(lectures=_lectures()))
    state.allow_lecture_tool = False

    assert provide_lecture_retrieval(state) is None


def test_lecture_list_is_absent_without_lectures(caplog):
    state = _lecture_chat_state(_dto(lectures=[]))

    with caplog.at_level(logging.WARNING):
        assert provide_lecture_list(state) is None

    # Indexed content without lectures in the DTO points at an outdated Artemis.
    assert "carries no lectures" in caplog.text


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
