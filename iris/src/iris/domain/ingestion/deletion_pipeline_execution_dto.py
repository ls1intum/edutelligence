from typing import List

from pydantic import Field

from iris.domain import PipelineExecutionDTO
from iris.domain.data.faq_dto import FaqDTO
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO


class LecturesDeletionExecutionDto(PipelineExecutionDTO):
    lecture_units: List[LectureUnitPageDTO] = Field(..., alias="pyrisLectureUnits")


class FaqDeletionExecutionDto(PipelineExecutionDTO):
    faq: FaqDTO = Field(..., alias="pyrisFaqWebhookDTO")
