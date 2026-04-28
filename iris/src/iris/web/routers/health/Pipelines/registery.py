from __future__ import annotations

from typing import Dict, Type

from iris.pipeline.autonomous_tutor_pipeline import AutonomousTutorPipeline
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.competency_extraction_pipeline import CompetencyExtractionPipeline
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.pipeline.inconsistency_check_pipeline import InconsistencyCheckPipeline
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.pipeline.rewriting_pipeline import RewritingPipeline
from iris.pipeline.tutor_suggestion_pipeline import TutorSuggestionPipeline
from iris.web.routers.health.Pipelines.features import Features

PipelineType = Type[
    ChatPipeline
    | CompetencyExtractionPipeline
    | InconsistencyCheckPipeline
    | TutorSuggestionPipeline
    | RewritingPipeline
    | LectureIngestionUpdatePipeline
    | FaqIngestionPipeline
    | AutonomousTutorPipeline
]

PIPELINE_BY_FEATURE: Dict[Features, PipelineType] = {
    Features.CHAT: ChatPipeline,
    Features.COMPETENCY_GENERATION: CompetencyExtractionPipeline,
    Features.INCONSISTENCY_CHECK: InconsistencyCheckPipeline,
    Features.TUTOR_SUGGESTION: TutorSuggestionPipeline,
    Features.REWRITING: RewritingPipeline,
    Features.LECTURE_INGESTION: LectureIngestionUpdatePipeline,
    Features.FAQ_INGESTION: FaqIngestionPipeline,
    Features.AUTONOMOUS_TUTOR: AutonomousTutorPipeline,
}
