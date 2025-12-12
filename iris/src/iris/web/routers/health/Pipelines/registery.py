from __future__ import annotations

from typing import Dict, Type

from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.pipelines import (
    CompetencyExtractionPipeline,
    CourseChatPipeline,
    ExerciseChatAgentPipeline,
    InconsistencyCheckPipeline,
    LectureChatPipeline,
    TextExerciseChatPipeline,
    TutorSuggestionPipeline,
)

PipelineType = Type[
    ExerciseChatAgentPipeline
    | TextExerciseChatPipeline
    | CourseChatPipeline
    | LectureChatPipeline
    | CompetencyExtractionPipeline
    | InconsistencyCheckPipeline
    | TutorSuggestionPipeline
    | LectureIngestionUpdatePipeline
    | FaqIngestionPipeline
]

PIPELINE_BY_FEATURE: Dict[Features, PipelineType] = {
    Features.PROGRAMMING_EXERCISE_CHAT: ExerciseChatAgentPipeline,
    Features.COURSE_CHAT: CourseChatPipeline,
    Features.TEXT_EXERCISE_CHAT: TextExerciseChatPipeline,
    Features.LECTURE_CHAT: LectureChatPipeline,
    Features.COMPETENCY_GENERATION: CompetencyExtractionPipeline,
    Features.INCONSISTENCY_CHECK: InconsistencyCheckPipeline,
    Features.TUTOR_SUGGESTION: TutorSuggestionPipeline,
    Features.LECTURE_INGESTION: LectureIngestionUpdatePipeline,
    Features.FAQ_INGESTION: FaqIngestionPipeline,
}
