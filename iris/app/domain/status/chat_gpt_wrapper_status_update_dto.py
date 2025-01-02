from app.domain.status.status_update_dto import StatusUpdateDTO


class ChatGPTWrapperStatusUpdateDTO(StatusUpdateDTO):
    """Data Transfer Object for ChatGPT wrapper status updates.
    This DTO extends the base StatusUpdateDTO to include the result of ChatGPT wrapper
    pipeline operations, facilitating communication between Artemis and raw ChatGPT models.
    """

    result: str
    """The result message or status of the ChatGPT wrapper pipeline operation."""
