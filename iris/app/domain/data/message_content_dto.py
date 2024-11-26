from typing import Union

from .tool_message_content_dto import ToolMessageContentDTO
from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO

MessageContentDTO = Union[
    TextMessageContentDTO,
    ImageMessageContentDTO,
    JsonMessageContentDTO,
    ToolMessageContentDTO,
]
