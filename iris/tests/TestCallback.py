from typing import List, Optional

from iris.domain.status.stage_dto import StageDTO
from iris.domain.status.stage_state_dto import StageStateEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.web.status.status_update import ExerciseChatStatusCallback


class TestExerciseChatCallback(ExerciseChatStatusCallback):
    """
    Test callback for ExerciseChatAgentPipeline.

    - Prevents HTTP calls
    - Captures final result, suggestions and token usage
    """

    def __init__(self):
        # Minimal stage setup required by StatusCallback logic
        stages = [
            StageDTO(
                weight=100,
                state=StageStateEnum.NOT_STARTED,
                name="Test Stage",
            )
        ]

        super().__init__(
            run_id="test-run-id",
            base_url="http://localhost",  # not used
            initial_stages=stages,
        )

        # Captured outputs
        self.final_result: Optional[str] = None
        self.suggestions: Optional[List[str]] = None
        self.tokens: Optional[List[TokenUsageDTO]] = None

        # Debug / tracing
        self.in_progress_messages: List[str] = []
        self.done_messages: List[str] = []
        self.error_messages: List[str] = []

        print("\n\n\nHallo Init\n\n\n")

    # ------------------------------------------------------------------
    # Disable network calls
    # ------------------------------------------------------------------

    def on_status_update(self):
        """Override to disable HTTP requests during tests."""

        print("\n\n\nHallo on status update\n\n\n")

        pass

    # ------------------------------------------------------------------
    # Capture progress
    # ------------------------------------------------------------------

    def in_progress(self, message: Optional[str] = None):
        self.in_progress_messages.append(message)
        super().in_progress(message)

        print("\n\n\nHallo in progress\n\n\n")


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

        print(final_result)
        print("\n\n\nHallo done\n\n\n")

        # Call parent to keep pipeline logic intact
        super().done(
            message=message,
            final_result=final_result,
            suggestions=suggestions,
            tokens=tokens,
            **kwargs,
        )

        self.final_result = final_result
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
