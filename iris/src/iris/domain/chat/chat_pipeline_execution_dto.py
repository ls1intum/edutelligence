from typing import List, Optional

from pydantic import Field, model_validator

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    LectureContextDTO,
)
from iris.domain.data.lecture_dto import PyrisLectureDTO
from iris.domain.data.metrics.student_metrics_dto import StudentMetricsDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO
from iris.pipeline.chat.iris_chat_mode import IrisChatMode


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    """
    Data Transfer Object for chat pipeline execution
    """

    chat_mode: IrisChatMode = Field(alias="chatMode")
    user: UserDTO
    course: CourseDTO

    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    metrics: Optional[StudentMetricsDTO] = None
    custom_instructions: Optional[str] = Field(alias="customInstructions", default="")

    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        alias="programmingExercise", default=None
    )
    text_exercise: Optional[TextExerciseDTO] = Field(alias="textExercise", default=None)
    lecture: Optional[PyrisLectureDTO] = None
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)
    context: Optional[List[LectureContextDTO]] = Field(
        default=None,
        description="Optional array of context objects (video/slides/combinedView) the student is currently viewing",
    )
    programming_exercise_submission: Optional[ProgrammingSubmissionDTO] = Field(
        alias="programmingExerciseSubmission", default=None
    )
    text_exercise_submission: str = Field(alias="textExerciseSubmission", default="")

    @model_validator(mode="after")
    def extract_lecture_unit_id_from_combined_view_context(self):
        """Extract lectureUnitId from a combinedView context if present.

        This populates the lecture_unit_id field from the combinedView context's
        nested slides/video objects, which is used for RAG filtering to scope
        retrieval to the specific lecture unit.
        """
        # Only extract if lecture_unit_id is not already set
        if self.lecture_unit_id is None and self.context:
            for ctx in self.context:
                if isinstance(ctx, CombinedViewContextDTO):
                    self.lecture_unit_id = ctx.lecture_unit_id
                    break
        return self
