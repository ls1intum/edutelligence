from pydantic import BaseModel, ConfigDict, Field

from iris.pipeline.chat.iris_chat_mode import IrisChatMode


class SuggestedContextDTO(BaseModel):
    """Context switch requested by the agent during a chat run.

    Carried on the final result status update so Artemis can move the
    session's active context to the entity the student asked about.
    The mode values serialize to the Artemis IrisChatMode enum names.
    """

    model_config = ConfigDict(populate_by_name=True)

    mode: IrisChatMode
    entity_id: int = Field(alias="entityId")
