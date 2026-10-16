"""A small, explicit tool-calling agent loop.

The loop asks the model, runs the tools it calls (one after another, in the
order the model listed them), appends their results and asks again, until the
model answers without tool calls. It replaces LangChain's AgentExecutor so that
Iris controls every message it sends, keeps provider data such as reasoning
items between steps, and can report tool activity and usage exactly.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Protocol, Sequence

from iris.common.logging_config import get_logger
from iris.common.pyris_message import IrisMessageRole, PyrisMessage, PyrisToolMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.data.tool_call_dto import ToolCallDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO
from iris.llm.agent.tools import (
    AgentTool,
    ToolArgumentError,
    format_tool_output,
    tool_error_text,
)
from iris.llm.iris_chat_model import message_text
from iris.tracing import observe

logger = get_logger(__name__)

DEFAULT_MAX_STEPS = 15

FINAL_ANSWER_INSTRUCTION = (
    "You have used the maximum number of tool calls for this message. Do not call "
    "any more tools. Answer the student now with the information you already have."
)


class ChatModel(Protocol):
    """The part of IrisChatModel the loop needs."""

    def chat(
        self,
        messages: list[PyrisMessage],
        tools: Optional[Sequence[Any]] = None,
        tool_choice: Optional[str] = None,
    ) -> PyrisMessage: ...


class ToolActivity(Protocol):
    """Receives tool lifecycle events (see ActivityTracker)."""

    def tool_started(self, name: str, arguments: dict) -> Optional[str]: ...

    def tool_finished(self, handle: Optional[str], name: str, output: Any) -> None: ...

    def tool_failed(self, handle: Optional[str], name: str) -> None: ...


@dataclass
class AgentRunResult:
    """The outcome of one agent run."""

    output: str
    steps: int
    tool_calls: int
    messages: list[PyrisMessage] = field(default_factory=list)
    hit_step_limit: bool = False


@dataclass
class AgentLoop:
    """Runs the model with tools until it gives a final answer."""

    model: ChatModel
    tools: list[AgentTool]
    max_steps: int = DEFAULT_MAX_STEPS
    strict_tools: bool = False
    # Whether the model honours tool_choice="none". When it does not (Ollama),
    # the forced final answer is requested without any tool definitions.
    supports_tool_choice: bool = True
    on_narration: Callable[[str], None] = lambda _text: None
    on_model_call: Callable[[], None] = lambda: None
    activity: Optional[ToolActivity] = None
    should_stop: Callable[[], bool] = lambda: False

    def __post_init__(self):
        self._tools_by_name = {tool.name: tool for tool in self.tools}
        self._schemas = [
            tool.openai_schema(strict=self.strict_tools) for tool in self.tools
        ]

    def run(self, messages: list[PyrisMessage]) -> AgentRunResult:
        conversation = list(messages)
        tool_calls = 0
        for step in range(1, self.max_steps + 1):
            response = self._call_model(conversation)
            calls = getattr(response, "tool_calls", None) or []
            if not calls:
                return AgentRunResult(
                    output=message_text(response),
                    steps=step,
                    tool_calls=tool_calls,
                    messages=conversation,
                )
            narration = message_text(response).strip()
            if narration:
                self.on_narration(narration)
            conversation.append(response)
            for call in calls:
                if self.should_stop():
                    raise AgentRunStopped()
                conversation.append(self._run_tool(call, step))
                tool_calls += 1
        logger.warning(
            "Agent reached the step limit (%d); asking for a final answer",
            self.max_steps,
        )
        final = self._force_final_answer(conversation)
        return AgentRunResult(
            output=message_text(final),
            steps=self.max_steps + 1,
            tool_calls=tool_calls,
            messages=conversation,
            hit_step_limit=True,
        )

    def _call_model(
        self, conversation: list[PyrisMessage], tool_choice: Optional[str] = None
    ) -> PyrisMessage:
        if self.should_stop():
            raise AgentRunStopped()
        try:
            return self.model.chat(
                conversation,
                self._schemas if self._schemas else None,
                tool_choice=tool_choice,
            )
        finally:
            # Usage is recorded also for a call that failed after the provider
            # reported it (see IncompleteModelResponse).
            self.on_model_call()

    def _force_final_answer(self, conversation: list[PyrisMessage]) -> PyrisMessage:
        if not self._schemas:
            return self._call_model(conversation)
        if self.supports_tool_choice:
            return self._call_model(conversation, tool_choice="none")
        reminder = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(textContent=FINAL_ANSWER_INSTRUCTION)],
            sentAt=datetime.now(),
        )
        try:
            return self.model.chat(conversation + [reminder], None)
        finally:
            self.on_model_call()

    def _run_tool(self, call: ToolCallDTO, step: int) -> PyrisToolMessage:
        name = call.function.name
        tool = self._tools_by_name.get(name)
        raw_arguments = call.function.arguments
        handle = None
        try:
            arguments = (
                raw_arguments
                if isinstance(raw_arguments, dict)
                else _parse_arguments(raw_arguments)
            )
            if self.activity is not None and tool is not None:
                handle = self.activity.tool_started(name, arguments)
            if tool is None:
                raise ToolArgumentError(
                    f"There is no tool named '{name}'. Available tools: "
                    + ", ".join(sorted(self._tools_by_name))
                )
            raw_output = _observed_call(tool, arguments)
            output = format_tool_output(raw_output)
        except AgentRunStopped:
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            # A failing tool must not abort the run: the model reads the error
            # and can still answer, possibly without that tool's data.
            logger.warning(
                "Tool call failed | step=%d tool=%s error=%s", step, name, error
            )
            if self.activity is not None and handle is not None:
                self.activity.tool_failed(handle, name)
            output = tool_error_text(error)
        else:
            logger.info(
                "Tool call | step=%d tool=%s | result_length=%d",
                step,
                name,
                len(output),
            )
            if self.activity is not None:
                self.activity.tool_finished(handle, name, raw_output)
        return PyrisToolMessage(
            contents=[
                ToolMessageContentDTO(
                    toolContent=output, toolName=name, toolCallId=call.id
                )
            ],
            sentAt=datetime.now(),
        )


class AgentRunStopped(Exception):
    """The run was stopped from outside (for example, cancelled)."""


def _parse_arguments(raw: Any) -> dict:
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ToolArgumentError(
            f"Tool arguments are not valid JSON: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise ToolArgumentError("Tool arguments must be a JSON object")
    return parsed


def _observed_call(tool: AgentTool, arguments: dict) -> Any:
    @observe(name=f"Tool: {tool.name}", as_type="tool")
    def call(arguments: dict) -> Any:
        return tool.call(arguments)

    return call(arguments)
