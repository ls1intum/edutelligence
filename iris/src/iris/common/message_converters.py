import json
from datetime import datetime
from typing import List, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)

from iris.common.pyris_message import (
    IrisMessageRole,
    PyrisAIMessage,
    PyrisMessage,
    PyrisToolMessage,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.data.tool_call_dto import FunctionDTO, ToolCallDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO


def convert_iris_message_to_langchain_message(
    iris_message: PyrisMessage,
) -> BaseMessage:
    if iris_message is None or len(iris_message.contents) == 0:
        raise ValueError("IrisMessage contents must not be empty")
    message = iris_message.contents[0]
    # Check if the message is of type TextMessageContentDTO
    if not isinstance(message, TextMessageContentDTO):
        raise ValueError("Message must be of type TextMessageContentDTO")
    match iris_message.sender:
        case IrisMessageRole.USER:
            return HumanMessage(content=message.text_content)
        case IrisMessageRole.ASSISTANT:
            if isinstance(iris_message, PyrisAIMessage):
                tool_calls = [
                    ToolCall(
                        name=tc.function.name,
                        args=tc.function.arguments,
                        id=tc.id,
                    )
                    for tc in iris_message.tool_calls
                ]
                return AIMessage(content=message.text_content, tool_calls=tool_calls)
            return AIMessage(content=message.text_content)
        case IrisMessageRole.SYSTEM:
            return SystemMessage(content=message.text_content)
        case IrisMessageRole.ARTIFACT:
            return SystemMessage(content="Previous suggestion: " + message.text_content)
        case _:
            raise ValueError(f"Unknown message role: {iris_message.sender}")


def convert_iris_message_to_langchain_human_message(
    iris_message: PyrisMessage,
) -> HumanMessage:
    if len(iris_message.contents) == 0:
        raise ValueError("IrisMessage contents must not be empty")
    message = iris_message.contents[0]
    # Check if the message is of type TextMessageContentDTO
    if not isinstance(message, TextMessageContentDTO):
        raise ValueError("Message must be of type TextMessageContentDTO")
    return HumanMessage(content=message.text_content)


def extract_text_from_iris_message(iris_message: PyrisMessage) -> str:
    if len(iris_message.contents) == 0:
        raise ValueError("IrisMessage contents must not be empty")
    message = iris_message.contents[0]
    # Check if the message is of type TextMessageContentDTO
    if not isinstance(message, TextMessageContentDTO):
        raise ValueError("Message must be of type TextMessageContentDTO")
    return message.text_content


def convert_langchain_tool_calls_to_iris_tool_calls(
    tool_calls: List[ToolCall],
) -> List[ToolCallDTO]:
    return [
        ToolCallDTO(
            function=FunctionDTO(
                name=tc["name"],
                arguments=json.dumps(tc["args"]),
            ),
            id=tc["id"],
        )
        for tc in tool_calls
    ]


def convert_langchain_message_to_iris_message(
    base_message: BaseMessage,
) -> PyrisMessage:
    type_to_role = {
        "human": IrisMessageRole.USER,
        "ai": IrisMessageRole.ASSISTANT,
        "system": IrisMessageRole.SYSTEM,
        "tool": IrisMessageRole.TOOL,
    }

    role = type_to_role.get(base_message.type)
    if role is None:
        raise ValueError(f"Unknown message type: {base_message.type}")

    if isinstance(base_message, (HumanMessage, SystemMessage)):
        contents = [TextMessageContentDTO(textContent=base_message.content)]
    elif isinstance(base_message, AIMessage):
        if base_message.tool_calls:
            contents = [TextMessageContentDTO(textContent=base_message.content)]
            tool_calls = convert_langchain_tool_calls_to_iris_tool_calls(
                base_message.tool_calls
            )
            return PyrisAIMessage(
                contents=contents,
                tool_calls=tool_calls,
                send_at=datetime.now(),
            )
        else:
            contents = [TextMessageContentDTO(textContent=base_message.content)]
    elif isinstance(base_message, ToolMessage):
        contents = [
            ToolMessageContentDTO(
                toolContent=base_message.content,
                toolName=base_message.additional_kwargs["name"],
                toolCallId=base_message.tool_call_id,
            )
        ]
        return PyrisToolMessage(
            contents=contents,
            send_at=datetime.now(),
        )
    else:
        raise ValueError(f"Unknown message type: {type(base_message)}")
    return PyrisMessage(
        contents=contents,
        sender=role,
        send_at=datetime.now(),
    )


def map_role_to_str(
    role: IrisMessageRole,
) -> Literal["user", "assistant", "system", "tool"]:
    match role:
        case IrisMessageRole.USER:
            return "user"
        case IrisMessageRole.ASSISTANT:
            return "assistant"
        case IrisMessageRole.SYSTEM:
            return "system"
        case IrisMessageRole.TOOL:
            return "tool"
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
        case "tool":
            return IrisMessageRole.TOOL
        case _:
            raise ValueError(f"Unknown message role: {role}")
