from iris.domain.status.status_update_dto import StatusUpdateDTO


class RewritingStatusUpdateDTO(StatusUpdateDTO):
    result: str = ""
