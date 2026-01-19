from typing import List, Optional

from iris.domain.status.stage_dto import StageDTO
from iris.domain.status.stage_state_dto import StageStateEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.web.status.status_update import ExerciseChatStatusCallback, PromptUserStatusCallback


class TestPromptUserStatusCallback(PromptUserStatusCallback):
    """
    Test callback for PromptUserAgentPipeline.

    - Prevents HTTP calls
    - Captures final result, suggestions and token usage
    """

    def __init__(self):

        super().__init__(
            run_id="test-run-id",
            base_url="http://localhost",  # not used
            initial_stages=None,
        )

        # Captured outputs
        self.final_result: Optional[str] = ""
        self.suggestions: Optional[List[str]] = None
        self.tokens: Optional[List[TokenUsageDTO]] = None

        # Debug / tracing
        self.in_progress_messages: List[str] = []
        self.done_messages: List[str] = []
        self.error_messages: List[str] = []

    # ------------------------------------------------------------------
    # Disable network calls
    # ------------------------------------------------------------------

    def on_status_update(self):
        """Override to disable HTTP requests during tests."""

        pass

    # ------------------------------------------------------------------
    # Capture progress
    # ------------------------------------------------------------------

    def in_progress(self, message: Optional[str] = None):
        self.in_progress_messages.append(message)
        super().in_progress(message)


    # ------------------------------------------------------------------
    # Capture final result
    # ------------------------------------------------------------------

    def done(
            self,
            message: Optional[str] = None,
            final_result: Optional[str] = None,
            suggestions: Optional[List[str]] = None,
            tokens: Optional[List[TokenUsageDTO]] = None,
            **kwargs,
    ):

        # Call parent to keep pipeline logic intact
        super().done(
            message=message,
            final_result=final_result,
            suggestions=suggestions,
            tokens=tokens,
            **kwargs,
        )

        self.final_result += (final_result or "") # Append new result of sub-pipeline instead of replacing
        self.suggestions = suggestions
        self.tokens = tokens
        self.done_messages.append(message)

    # ------------------------------------------------------------------
    # Capture errors
    # ------------------------------------------------------------------

    def error(
            self,
            message: str,
            exception=None,
            tokens: Optional[List[TokenUsageDTO]] = None,
    ):
        self.error_messages.append(message)
        super().error(message, exception, tokens)
