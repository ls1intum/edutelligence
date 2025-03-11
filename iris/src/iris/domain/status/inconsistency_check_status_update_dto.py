from iris.domain.status.status_update_dto import StatusUpdateDTO


class InconsistencyCheckStatusUpdateDTO(StatusUpdateDTO):
    result: str = ""
