from typing import List, Optional

from iris.common.token_usage_dto import TokenUsageDTO
from iris.web.status.status_update import AskUserStatusCallback


class AskUserStatusCallbackMock(AskUserStatusCallback):
    """
    Test callback.

    - Prevents HTTP calls
    - Captures final result and token usage
    """

    def __init__(self):
        super().__init__(
            run_id="test-run-id",
            base_url="http://localhost",  # not used
        )

        # Captured outputs
        self.final_result: str = ""
        self.tokens: Optional[List[TokenUsageDTO]] = None

        # Debug / tracing
        self.update_calls: List[dict] = []
        self.fail_messages: List[Optional[str]] = []

    # ------------------------------------------------------------------
    # Disable network calls
    # ------------------------------------------------------------------

    def on_status_update(self):
        """Override to disable HTTP requests during tests."""

        pass

    # ------------------------------------------------------------------
    # Capture progress / final result
    # ------------------------------------------------------------------

    def update(self, **fields) -> bool:
        self.update_calls.append(fields)

        result = fields.get("result")
        if result is not None:
            # Append new result of sub-pipeline instead of replacing
            self.final_result += result
        if "tokens" in fields:
            self.tokens = fields["tokens"]

        return super().update(**fields)

    # ------------------------------------------------------------------
    # Capture errors
    # ------------------------------------------------------------------

    def fail(self, message=None, code=None, tokens=None, **fields) -> bool:
        self.fail_messages.append(message)
        return super().fail(message, code, tokens, **fields)
