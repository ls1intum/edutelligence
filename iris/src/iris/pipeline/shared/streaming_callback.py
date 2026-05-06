from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from iris.common.logging_config import get_logger
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)

# Send a streaming update every this many tokens.
_TOKENS_PER_SEND = 5

# Don't start streaming until we have at least this many characters accumulated —
# avoids flashing a half-word bubble at the user.
_MIN_CHARS_TO_STREAM = 30


class StreamingStatusCallback(BaseCallbackHandler):
    """LangChain callback that streams partial LLM output to the client.

    On every LLM call start the accumulator is reset so routing/tool-call
    LLM invocations (which emit zero content tokens) leave no residue.
    On each new token the accumulated text is sent via in_progress(chat_message=...)
    every _TOKENS_PER_SEND tokens once _MIN_CHARS_TO_STREAM characters have built up.
    """

    def __init__(self, status_callback: StatusCallback) -> None:
        super().__init__()
        self._status_callback = status_callback
        self._accumulated = ""
        self._token_count = 0

    # ------------------------------------------------------------------
    # LangChain callback hooks
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Reset state at the start of every LLM call."""
        self._accumulated = ""
        self._token_count = 0

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """Accumulate token and periodically push a streaming update."""
        self._accumulated += token
        self._token_count += 1

        if (
            self._token_count % _TOKENS_PER_SEND == 0
            and len(self._accumulated) >= _MIN_CHARS_TO_STREAM
        ):
            self._send()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Send a final update when the LLM call ends (if content was generated)."""
        if self._accumulated and len(self._accumulated) >= _MIN_CHARS_TO_STREAM:
            self._send()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self) -> None:
        try:
            self._status_callback.in_progress(
                "Generating response...",
                chat_message=self._accumulated,
            )
        except Exception:  # pylint: disable=broad-except
            logger.debug("Failed to send streaming status update", exc_info=True)
