from __future__ import annotations

from typing import Dict, Type

from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.competency_extraction_pipeline import CompetencyExtractionPipeline
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.pipeline.inconsistency_check_pipeline import InconsistencyCheckPipeline
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.tutor_suggestion_pipeline import TutorSuggestionPipeline
from iris.web.routers.health.Pipelines.features import Features

PipelineType = Type[
    ChatPipeline
    | CompetencyExtractionPipeline
    | InconsistencyCheckPipeline
    | TutorSuggestionPipeline
    | LectureUnitPageIngestionPipeline
    | FaqIngestionPipeline
]

PIPELINE_BY_FEATURE: Dict[Features, PipelineType] = {
    Features.CHAT: ChatPipeline,
    Features.COMPETENCY_GENERATION: CompetencyExtractionPipeline,
    Features.INCONSISTENCY_CHECK: InconsistencyCheckPipeline,
    Features.TUTOR_SUGGESTION: TutorSuggestionPipeline,
    Features.LECTURE_INGESTION: LectureUnitPageIngestionPipeline,
    Features.FAQ_INGESTION: FaqIngestionPipeline,
}
