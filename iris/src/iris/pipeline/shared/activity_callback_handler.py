from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from iris.common.logging_config import get_logger
from iris.domain.status.activity_dto import ActivityKind
from iris.pipeline.shared.activity_tracker import ActivityTracker
from iris.tools.activity_metadata import curate_detail, curate_result

logger = get_logger(__name__)


class ActivityCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that mirrors tool runs into an ActivityTracker."""

    def __init__(self, tracker: ActivityTracker):
        super().__init__()
        self._tracker = tracker
        self._tool_runs: dict[Any, tuple[str, str]] = {}

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
