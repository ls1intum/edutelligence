from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from iris.common.token_logprob_dto import TokenLogprobEntry
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.message_content_dto import MessageContentDto
from iris.domain.data.tool_call_dto import ToolCallDTO
from iris.domain.data.tool_message_content_dto import ToolMessageContentDTO


class IrisMessageRole(str, Enum):
    USER = "USER"
    ASSISTANT = "LLM"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"
    ARTIFACT = "ARTIFACT"
    COMMAND = "COMMAND"
    CTXSWAP = "CTXSWAP"
    # Stored summary of the earlier conversation (see pipeline/shared/compaction.py).
    SUMMARY = "SUMMARY"


class PyrisMessage(BaseModel):
    """A single message exchanged with an LLM, with optional token metadata."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = Field(default=None)
    token_usage: TokenUsageDTO = Field(default_factory=TokenUsageDTO)
    sent_at: datetime | None = Field(alias="sentAt", default=None)
    sender: IrisMessageRole
    contents: List[MessageContentDto] = Field(default=[])
    # Per-token log-probabilities of the generated content, populated only when
    # the model exposes them (see CompletionArguments.logprobs). Internal signal
    # used for confidence scoring; excluded from serialization to Artemis.
    token_logprobs: Optional[List[float]] = Field(default=None, exclude=True)
    # Rich per-token data including the top-k alternative candidates, populated
    # only when the model returns them (see CompletionArguments.top_logprobs).
    # Drives the uncertainty-based confidence strategy; excluded like above.
    token_logprob_entries: Optional[List[TokenLogprobEntry]] = Field(
        default=None, exclude=True
    )
    # The provider's own output items of this response (Responses API: reasoning
    # items with encrypted content, assistant message items and function calls),
    # in their original order. Kept only within one agent run, so the next request
    # of the tool loop can send them back unchanged; never serialized to Artemis.
    provider_items: Optional[List[dict[str, Any]]] = Field(default=None, exclude=True)
    # Reasoning text an OpenAI-compatible server (vLLM: gpt-oss, Qwen) returned
    # next to a tool call; sent back within the same tool loop when the model
    # entry enables it. Never serialized to Artemis.
    reasoning_content: Optional[str] = Field(default=None, exclude=True)

    def __str__(self):
        return f"{self.sender.lower()}: {self.contents}"


class PyrisAIMessage(PyrisMessage):
    model_config = ConfigDict(populate_by_name=True)
    sender: IrisMessageRole = IrisMessageRole.ASSISTANT
    tool_calls: Optional[List[ToolCallDTO]] = Field(alias="toolCalls")


class PyrisToolMessage(PyrisMessage):
    model_config = ConfigDict(populate_by_name=True)
    sender: IrisMessageRole = IrisMessageRole.TOOL
    contents: List[ToolMessageContentDTO] = Field(default=[])
