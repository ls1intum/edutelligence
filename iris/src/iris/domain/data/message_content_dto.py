from typing import Union

from ...domain.data.image_message_content_dto import ImageMessageContentDTO
from ...domain.data.json_message_content_dto import JsonMessageContentDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from .tool_message_content_dto import ToolMessageContentDTO

MessageContentDto = Union[
    TextMessageContentDTO,
    ImageMessageContentDTO,
    JsonMessageContentDTO,
    ToolMessageContentDTO,
]
