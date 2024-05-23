from typing import Optional

from app.domain.chat.chat_pipeline_execution_base_data_dto import ChatPipelineExecutionBaseDataDTO
from app.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from app.domain.data.course_dto import CourseDTO
from app.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from app.domain.data.programming_submission_dto import ProgrammingSubmissionDTO


class TutorChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    submission: Optional[ProgrammingSubmissionDTO] = None
    exercise: ProgrammingExerciseDTO
    course: CourseDTO
    base: ChatPipelineExecutionBaseDataDTO
