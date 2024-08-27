from typing import Optional

from app.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from app.domain.data.course_dto import CourseDTO
from app.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from app.domain.data.programming_submission_dto import ProgrammingSubmissionDTO


class ProgrammingExerciseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    submission: Optional[ProgrammingSubmissionDTO] = None
    exercise: ProgrammingExerciseDTO
    course: CourseDTO
