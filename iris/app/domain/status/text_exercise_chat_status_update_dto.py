from app.domain.status.status_update_dto import StatusUpdateDTO


class TextExerciseChatStatusUpdateDTO(StatusUpdateDTO):
    result: str
