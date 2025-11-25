from pydantic import Field

from iris.domain import PipelineExecutionDTO
from iris.domain.data.faq_dto import FaqDTO
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO


class IngestionPipelineExecutionDto(PipelineExecutionDTO):
    lecture_unit: LectureUnitPageDTO = Field(alias="pyrisLectureUnit")
    lecture_unit_id: int = Field(alias="lectureUnitId")


class FaqIngestionPipelineExecutionDto(PipelineExecutionDTO):
    faq: FaqDTO = Field(..., alias="pyrisFaqWebhookDTO")
