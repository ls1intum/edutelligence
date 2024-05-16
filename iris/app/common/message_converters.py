from datetime import datetime
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from app.domain.data.text_message_content_dto import TextMessageContentDTO
from app.domain.pyris_message import PyrisMessage, IrisMessageRole


def convert_iris_message_to_langchain_message(
    iris_message: PyrisMessage,
) -> BaseMessage:
    if len(iris_message.contents) == 0:
        raise ValueError("IrisMessage contents must not be empty")
    message = iris_message.contents[0]
    # Check if the message is of type TextMessageContentDTO
    if not isinstance(message, TextMessageContentDTO):
        raise ValueError("Message must be of type TextMessageContentDTO")
    match iris_message.sender:
        case IrisMessageRole.USER:
            return HumanMessage(content=message.text_content)
        case IrisMessageRole.ASSISTANT:
            return AIMessage(content=message.text_content)
        case IrisMessageRole.SYSTEM:
            return SystemMessage(content=message.text_content)
        case _:
            raise ValueError(f"Unknown message role: {iris_message.sender}")

def convert_langchain_message_to_iris_message(
    base_message: BaseMessage,
) -> PyrisMessage:
    match base_message.type:
        case "human":
            role = IrisMessageRole.USER
        case "ai":
            role = IrisMessageRole.ASSISTANT
        case "system":
            role = IrisMessageRole.SYSTEM
        case _:
            raise ValueError(f"Unknown message type: {base_message.type}")
    contents = [TextMessageContentDTO(textContent=base_message.content)]
    return PyrisMessage(
        contents=contents,
        sender=role,
        send_at=datetime.now(),
    )


def map_role_to_str(role: IrisMessageRole) -> Literal["user", "assistant", "system"]:
    match role:
        case IrisMessageRole.USER:
            return "user"
        case IrisMessageRole.ASSISTANT:
            return "assistant"
        case IrisMessageRole.SYSTEM:
            return "system"
        case _:
            raise ValueError(f"Unknown message role: {role}")


def map_str_to_role(role: str) -> IrisMessageRole:
    match role:
        case "user":
            return IrisMessageRole.USER
        case "assistant":
            return IrisMessageRole.ASSISTANT
        case "system":
            return IrisMessageRole.SYSTEM
        case _:
            raise ValueError(f"Unknown message role: {role}")
