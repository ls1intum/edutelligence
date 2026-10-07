from pydantic import BaseModel, ConfigDict, Field


class CompactionDTO(BaseModel):
    """A summary of the conversation up to and including one message.

    Artemis stores it as a SUMMARY message with this JSON content.
    """

    model_config = ConfigDict(populate_by_name=True)

    summary: str
    covers_through_message_id: int = Field(alias="coversThroughMessageId")
