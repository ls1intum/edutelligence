import pytest
from pydantic import ValidationError

from iris.domain.chat.ask_user_chat.ask_user_chat_pipeline_execution_dto import (
    AskUserPipelineExecutionDTO,
)
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.user_dto import UserDTO
from iris.pipeline.chat.iris_chat_mode import IrisChatMode

BASE_FIELDS = {
    "chatMode": IrisChatMode.EXERCISE,
    "user": UserDTO(id=1, firstName="A", lastName="B", memirisEnabled=False),
    "course": CourseDTO(id=1, name="Course", description=None),
    "settings": None,
}


def test_parses_camel_case_question_fields_by_alias():
    dto = AskUserPipelineExecutionDTO(
        **BASE_FIELDS,
        minQuestions=2,
        maxQuestions=5,
        questionsAsked=3,
    )

    assert dto.min_questions == 2
    assert dto.max_questions == 5
    assert dto.questions_asked == 3


def test_missing_required_question_fields_raise():
    with pytest.raises(ValidationError):
        AskUserPipelineExecutionDTO(**BASE_FIELDS)


def test_inherits_chat_pipeline_execution_dto_fields():
    dto = AskUserPipelineExecutionDTO(
        **BASE_FIELDS,
        minQuestions=1,
        maxQuestions=1,
        questionsAsked=0,
    )

    # Fields defined on the ChatPipelineExecutionDTO base class must still work.
    assert dto.chat_mode == IrisChatMode.EXERCISE
    assert dto.chat_history == []
    assert dto.programming_exercise is None
