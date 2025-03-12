from iris.domain.data.competency_dto import Competency
from iris.domain.status.status_update_dto import StatusUpdateDTO


class CompetencyExtractionStatusUpdateDTO(StatusUpdateDTO):
    result: list[Competency] = []
