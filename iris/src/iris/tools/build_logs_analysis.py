"""Tool for analyzing build logs."""

import re
from typing import Callable, Optional

from ..domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_build_logs_analysis(
    submission: Optional[ProgrammingSubmissionDTO], callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that analyzes build logs.

    Args:
        submission: Programming submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns build logs analysis.
    """

    def redact_sensitive_info(text: str) -> str:
        """Redact sensitive information from log messages."""
        # Redact common patterns for secrets and tokens
        patterns = [
            (
                r"(api[_-]?key|apikey|api[_-]?secret)['\"]?\s*[:=]\s*['\"]?[\w\-]+",
                "[REDACTED_API_KEY]",
            ),
            (
                r"(password|passwd|pwd)['\"]?\s*[:=]\s*['\"]?[^\s'\"]+",
                "[REDACTED_PASSWORD]",
            ),
            (
                r"(token|auth[_-]?token|access[_-]?token)['\"]?\s*[:=]\s*['\"]?[\w\-\.]+",
                "[REDACTED_TOKEN]",
            ),
            (
                r"(secret|private[_-]?key)['\"]?\s*[:=]\s*['\"]?[\w\-]+",
                "[REDACTED_SECRET]",
            ),
            (r"Bearer\s+[\w\-\.]+", "Bearer [REDACTED_TOKEN]"),
            (r"(ssh-rsa|ssh-ed25519)\s+[\w+/=]+", "[REDACTED_SSH_KEY]"),
            # Redact potential AWS credentials
            (r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_ACCESS_KEY]"),
            (
                r"aws[_-]?secret[_-]?access[_-]?key['\"]?\s*[:=]\s*['\"]?[\w+/=]+",
                "[REDACTED_AWS_SECRET]",
            ),
        ]

        result = text
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def get_build_logs_analysis_tool() -> str:
        """
        # Build Logs Analysis Tool

        ## Purpose
        Analyze CI/CD build logs for debugging and code quality feedback.

        ## Retrieved Information
        - Build status (successful or failed)
        - If failed:
          - Error messages
          - Warning messages
          - Timestamps for log entries

        Returns:
            str: Build logs analysis result.
        """
        # TODO: This pipeline needs to be extended to actually analyze the logs,
        # not just return them. Should include pattern detection for common errors,
        # suggestions for fixes, and categorization of error types.
        try:
            callback.in_progress("Analyzing build logs ...")
        except ValueError:
            # Callback might already be in progress state
            pass
        if not submission:
            return "No build logs available."
        # Safely access build_failed attribute with fallback
        build_failed = bool(getattr(submission, "build_failed", False))
        # Safely access build_log_entries with fallback to empty list
        build_log_entries = getattr(submission, "build_log_entries", None) or []
        if not build_failed:
            return "The build was successful."
        # Process log entries safely
        lines: list[str] = []
        max_lines = 200
        max_line_length = 500
        for log in build_log_entries:
            # Safely access message attribute
            message = getattr(log, "message", None)
            # Use message if it's a string, otherwise convert log to string
            text = message if isinstance(message, str) else str(log)
            # Filter out noise (lines with ~~~~~~~~)
            if "~~~~~~~~~" in text:
                continue
            # Redact sensitive information
            text = redact_sensitive_info(text)
            # Truncate individual lines if too long
            if len(text) > max_line_length:
                text = text[:max_line_length] + "... [truncated]"
            lines.append(text)
            # Stop if we've collected enough lines
            if len(lines) >= max_lines:
                lines.append(
                    f"... [{len(build_log_entries) - max_lines} more log entries truncated]"
                )
                break
        if not lines:
            return "The build failed, but no build logs were available."
        return "\n".join(lines)

    return get_build_logs_analysis_tool
