import json
from datetime import datetime
from typing import List, Literal, Optional

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
from iris.domain.data.command_marker import describe_command_marker
from iris.domain.data.context_switch_marker import (
    ContextSwitchMarker,
    ContextSwitchTransition,
)
from iris.domain.data.json_message_content_dto import JsonMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.data.tool_call_dto import FunctionDTO, ToolCallDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO


def _context_switch_text(content: JsonMessageContentDTO) -> str:
    marker = ContextSwitchMarker.model_validate(content.json_content or {})
    name = marker.name
    entity_id = marker.entity_id
    match marker.transition:
        case ContextSwitchTransition.ADDED:
            text = f"The student added the context '{name}' with ID '{entity_id}' to the chat."
        case ContextSwitchTransition.REMOVED:
            text = (
                "The student removed the active context and returned to the "
                "course-level chat."
            )
        case ContextSwitchTransition.CHANGED:
            text = f"The student switched the chat context to '{name}' with ID '{entity_id}'."
        case _:
            text = f"The student changed the chat context to '{name}' with ID '{entity_id}'."
    return f"[context_switch] {text}"


def _text_message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


def normalize_history_message(iris_message: PyrisMessage) -> PyrisMessage:
    """Turn a stored chat message into the message the model receives.

    Context-switch and command markers become system text, earlier tutor
    suggestions (ARTIFACT) become a system note. User, assistant and system text
    pass through unchanged; an assistant message keeps its tool calls.
    """
    if iris_message is None or len(iris_message.contents) == 0:
        raise ValueError("IrisMessage contents must not be empty")
    message = iris_message.contents[0]

    if iris_message.sender == IrisMessageRole.CTXSWAP:
        if not isinstance(message, JsonMessageContentDTO):
            raise ValueError("CTXSWAP message must be of type JsonMessageContentDTO")
        return _text_message(IrisMessageRole.SYSTEM, _context_switch_text(message))

    if iris_message.sender == IrisMessageRole.COMMAND:
        # COMMAND markers (e.g. past point-outs) arrive as the JSON Artemis stored them as; the
        # wording the agent reads is built here so it stays next to the prompts.
        if not isinstance(message, JsonMessageContentDTO):
            raise ValueError("COMMAND message must be of type JsonMessageContentDTO")
        return _text_message(
            IrisMessageRole.SYSTEM, describe_command_marker(message.json_content or {})
        )

    if isinstance(iris_message, PyrisAIMessage) and iris_message.tool_calls:
        return iris_message
    text = "\n\n".join(
        part
        for part in (_content_text(content) for content in iris_message.contents)
        if part
    )
    match iris_message.sender:
        case IrisMessageRole.USER:
            return _text_message(IrisMessageRole.USER, text)
        case IrisMessageRole.ASSISTANT:
            return _text_message(IrisMessageRole.ASSISTANT, text)
        case IrisMessageRole.SYSTEM:
            return _text_message(IrisMessageRole.SYSTEM, text)
        case IrisMessageRole.ARTIFACT:
            return _text_message(IrisMessageRole.SYSTEM, "Previous suggestion: " + text)
        case _:
            raise ValueError(f"Unknown message role: {iris_message.sender}")


def _content_text(content) -> str:
    """The text a model reads for one message content (text, or a described quiz)."""
    if isinstance(content, TextMessageContentDTO):
        return content.text_content or ""
    if isinstance(content, JsonMessageContentDTO):
        return describe_json_content(content.json_content)
    raise ValueError(f"Unsupported message content: {type(content).__name__}")


def _describe_mcq(question: dict, number: Optional[int] = None) -> str:
    label = "Quiz question" if number is None else f"Quiz question {number}"
    question_text = question.get("question", "")
    lines = [f"{label} shown to the student: {question_text}"]
    options = question.get("options") or []
    for index, option in enumerate(options, start=1):
        marker = " (correct)" if option.get("correct") else ""
        option_text = option.get("text", "")
        lines.append(f"  {index}) {option_text}{marker}")
    explanation = question.get("explanation")
    if explanation:
        lines.append(f"  Explanation: {explanation}")
    response = question.get("response") or {}
    selected = response.get("selectedIndex")
    if (
        response.get("submitted")
        and isinstance(selected, int)
        and 0 <= selected < len(options)
    ):
        verdict = "correct" if options[selected].get("correct") else "incorrect"
        lines.append(f"  The student answered option {selected + 1} ({verdict}).")
    else:
        lines.append("  The student has not answered it yet.")
    return "\n".join(lines)


def describe_json_content(json_content) -> str:
    """Describe structured message content (quiz widgets) as text for the model.

    Without this, an assistant message that only consists of a quiz could not be
    sent to the model at all, and the follow-up turn failed.
    """
    if not isinstance(json_content, dict):
        return json.dumps(json_content, ensure_ascii=False)[:2000]
    kind = json_content.get("type")
    if kind == "mcq":
        return "[" + _describe_mcq(json_content) + "]"
    if kind == "mcq-set":
        questions = json_content.get("questions") or []
        return (
            "["
            + "\n".join(
                _describe_mcq(question, number)
                for number, question in enumerate(questions, start=1)
            )
            + "]"
        )
    return (
        "[Structured content: "
        + json.dumps(json_content, ensure_ascii=False)[:2000]
        + "]"
    )


def convert_iris_message_to_langchain_message(
    iris_message: PyrisMessage,
) -> BaseMessage:
    normalized = normalize_history_message(iris_message)
    text = normalized.contents[0].text_content
    match normalized.sender:
        case IrisMessageRole.USER:
            return HumanMessage(content=text)
        case IrisMessageRole.ASSISTANT:
            if isinstance(normalized, PyrisAIMessage) and normalized.tool_calls:
                tool_calls = [
                    ToolCall(
                        name=tc.function.name,
                        args=tc.function.arguments,
                        id=tc.id,
                    )
                    for tc in normalized.tool_calls
                ]
                return AIMessage(content=text, tool_calls=tool_calls)
            return AIMessage(content=text)
        case _:
            return SystemMessage(content=text)


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
        # CTXSWAP and COMMAND markers carry instructions for the LLM and are rendered as a
        # SystemMessage in convert_iris_message_to_langchain_message; mirror that
        # here so the direct OpenAI/Ollama paths don't reject a valid role.
        case IrisMessageRole.SYSTEM | IrisMessageRole.CTXSWAP | IrisMessageRole.COMMAND:
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
