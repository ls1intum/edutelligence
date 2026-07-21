import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, Sequence, Type, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from iris.common.logging_config import get_logger
from iris.common.pyris_message import PyrisMessage
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.external.model import (
    ChatModel,
    CompletionModel,
    EmbeddingModel,
    LanguageModel,
)
from iris.llm.llm_manager import LlmManager
from iris.llm.request_handler.request_handler_interface import RequestHandler

logger = get_logger(__name__)


def _record_qa_spend(usage) -> None:
    ledger_path = os.environ.get("IRIS_QA_SPEND_LEDGER")
    if not ledger_path:
        return
    from iris.qa.cost import (  # pylint: disable=import-outside-toplevel
        BudgetGuard,
        ModelRate,
        SpendLedger,
    )

    try:
        rates = json.loads(os.environ["IRIS_QA_SPEND_RATES"])
        raw_rate = rates[usage.model_info]
        rate = ModelRate(
            model=usage.model_info,
            input_per_million=Decimal(str(raw_rate["input"])),
            output_per_million=Decimal(str(raw_rate["output"])),
        )
        hard_limit = Decimal(os.environ["IRIS_QA_SPEND_HARD_LIMIT_USD"])
        run_id = os.environ["IRIS_QA_SPEND_RUN_ID"]
        scenario_id = os.environ["IRIS_QA_SPEND_SCENARIO_ID"]
        pipeline = os.environ["IRIS_QA_SPEND_PIPELINE"]
    except (
        KeyError,
        TypeError,
        ValueError,
        InvalidOperation,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError("Invalid direct QA spend-ledger configuration") from error
    BudgetGuard(SpendLedger(Path(ledger_path)), hard_limit).record_usage(
        run_id=run_id,
        scenario_id=scenario_id,
        pipeline=pipeline,
        rate=rate,
        input_tokens=usage.num_input_tokens,
        output_tokens=usage.num_output_tokens,
    )


def _record_qa_token_usage(usage) -> None:
    """Persist provider usage immediately for crash-safe paid QA accounting."""
    path = os.environ.get("IRIS_QA_PROVIDER_USAGE_LOG")
    if not path and not os.environ.get("IRIS_QA_SPEND_LEDGER"):
        return
    if usage.num_input_tokens is None or usage.num_output_tokens is None:
        raise RuntimeError("QA provider response omitted token usage")
    if usage.num_input_tokens == 0 and usage.num_output_tokens == 0:
        raise RuntimeError(
            "QA provider response reported no token usage; failing closed"
        )
    _record_qa_spend(usage)
    if not path:
        return
    payload = {
        "model": usage.model_info,
        "input_tokens": usage.num_input_tokens,
        "output_tokens": usage.num_output_tokens,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(payload, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    with open(path, "r", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    totals = {
        "input": sum(item["input_tokens"] for item in records),
        "output": sum(item["output_tokens"] for item in records),
    }
    for kind in ("input", "output"):
        raw_limit = os.environ.get(f"IRIS_QA_MAX_TOTAL_{kind.upper()}_TOKENS")
        if raw_limit is not None and totals[kind] > int(raw_limit):
            raise RuntimeError(
                f"QA worker exceeded total {kind} token ceiling: "
                f"{totals[kind]} > {raw_limit}"
            )


def _record_qa_usage(message: PyrisMessage) -> None:
    _record_qa_token_usage(message.token_usage)


class LlmRequestHandler(RequestHandler):
    """Request handler that selects the first model with a matching id."""

    model_id: str
    llm_manager: LlmManager | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        model_id: str,
    ) -> None:
        super().__init__(
            model_id=model_id,
            llm_manager=None,
        )
        self.model_id = model_id
        self.llm_manager = LlmManager()

    def complete(self, prompt: str, arguments: CompletionArguments) -> str:
        llm = self._select_model(CompletionModel)
        return llm.complete(prompt, arguments)

    def chat(
        self,
        messages: list[PyrisMessage],
        arguments: CompletionArguments,
        tools: Optional[
            Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]]
        ],
    ) -> PyrisMessage:
        llm = self._select_model(ChatModel)
        try:
            message = llm.chat(messages, arguments, tools)
        except RuntimeError as error:
            rejected_usage = getattr(error, "qa_token_usage", None)
            if rejected_usage is not None:
                rejected_usage.model_info = llm.model
                _record_qa_token_usage(rejected_usage)
            raise
        message.token_usage.model_info = llm.model
        message.token_usage.cost_per_million_input_token = (
            llm.cost_per_million_input_token
        )
        message.token_usage.cost_per_million_output_token = (
            llm.cost_per_million_output_token
        )
        _record_qa_usage(message)
        return message

    def embed(self, text: str) -> list[float]:
        llm = self._select_model(EmbeddingModel)
        return llm.embed(text)

    def split_text_semantically(
        self,
        text: str,
        breakpoint_threshold_type: Literal[
            "percentile", "standard_deviation", "interquartile", "gradient"
        ] = "gradient",
        breakpoint_threshold_amount: float = 95.0,
        min_chunk_size: int = 512,
    ):
        llm = self._select_model(EmbeddingModel)

        return llm.split_text_semantically(
            text,
            breakpoint_threshold_type,
            breakpoint_threshold_amount,
            min_chunk_size,
        )

    def _select_model(self, type_filter: type) -> LanguageModel:
        """Select the first model that matches the requested id"""
        # Get all LLMs from the manager
        all_llms = self.llm_manager.entries

        # Filter LLMs by type and id
        matching_llms = [
            llm
            for llm in all_llms
            if isinstance(llm, type_filter) and llm.id == self.model_id
        ]

        if not matching_llms:
            raise ValueError(f"No {type_filter.__name__} found with id {self.model_id}")

        # Select the first matching LLM
        llm = matching_llms[0]

        logger.debug("Selected model | id=%s", llm.id)
        return llm

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, BaseTool]],
    ) -> LanguageModel:
        """Bind the provided tools to the selected ChatModel.

        Args:
            tools: A sequence of tools to bind. Can be one of:
                - Dict[str, Any]: Tool configuration dictionary
                - Type[BaseModel]: Pydantic model class
                - Callable: Function to be used as a tool
                - BaseTool: LangChain tool instance

        Returns:
            LanguageModel: The selected chat model with tools bound

        Raises:
            ValueError: If tools sequence is empty or contains unsupported tool types
            TypeError: If selected model doesn't support tool binding
        """
        if not tools:
            raise ValueError("Tools sequence cannot be empty")

        llm = self._select_model(ChatModel)
        if not hasattr(llm, "bind_tools"):
            raise TypeError(f"Selected model {llm.id} doesn't support tool binding")

        llm.bind_tools(tools)
        return llm
