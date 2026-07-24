from typing import Any, Callable, Optional

from langchain_core.callbacks import BaseCallbackHandler

from iris.common.logging_config import get_logger
from iris.domain.status.activity_dto import ActivityKind
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.tools.activity_metadata import curate_detail, curate_result

logger = get_logger(__name__)


def _visible_message_text(content: Any) -> str:
    """Extract visible text from a LangChain message content value."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        item if isinstance(item, str) else item.get("text", "")
        for item in content
        if isinstance(item, (str, dict))
    ]
    return "".join(part for part in parts if isinstance(part, str)).strip()


class ActivityCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that mirrors tool runs into an ActivityTracker."""

    def __init__(
        self,
        tracker: ActivityTracker,
        narrate: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self._tracker = tracker
        self._narrate = narrate
        self._tool_runs: dict[Any, tuple[str, str]] = {}

    def on_agent_action(self, action: Any, **_kwargs) -> None:
        # Fires BEFORE the tool executes, so the user reads the narration first,
        # then sees the tool chip start. The step-boundary fallback in the agent
        # loop dedupes against this emission.
        if self._narrate is None:
            return
        try:
            message_log = getattr(action, "message_log", None)
            if not message_log:
                return
            text = _visible_message_text(getattr(message_log[-1], "content", ""))
            if text:
                self._narrate(text)
        except Exception:
            logger.exception("Activity callback failed during agent action")

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any,
        inputs: dict[str, Any] | None = None,
        **_kwargs,
    ) -> None:
        try:
            tool_name = serialized.get("name") or "unknown"
            tool_inputs = inputs if inputs is not None else {"input": input_str}
            detail = curate_detail(tool_name, tool_inputs)
            item_id = self._tracker.start(ActivityKind.TOOL, tool_name, detail=detail)
            self._tool_runs[run_id] = (item_id, tool_name)
        except Exception:
            logger.exception("Activity callback failed during tool start")

    def on_tool_end(self, output: Any, *, run_id: Any, **_kwargs) -> None:
        try:
            tool_run = self._tool_runs.pop(run_id, None)
            if tool_run is None:
                logger.debug("Ignoring tool end for unknown run id %s", run_id)
                return
            item_id, tool_name = tool_run
            self._tracker.finish(item_id, result=curate_result(tool_name, output))
        except Exception:
            logger.exception("Activity callback failed during tool end")

    def on_tool_error(self, error: BaseException, *, run_id: Any, **_kwargs) -> None:
        try:
            del error
            tool_run = self._tool_runs.pop(run_id, None)
            if tool_run is None:
                logger.debug("Ignoring tool error for unknown run id %s", run_id)
                return
            item_id = tool_run[0]
            self._tracker.fail(item_id)
        except Exception:
            logger.exception("Activity callback failed during tool error")
