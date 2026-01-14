"""
Centralized logging configuration for Iris.

Provides:
- Request ID context tracking via contextvars
- Custom formatter with abbreviated logger names and aligned output
- Setup function for consistent logging across the application
"""

import logging
import secrets
import sys
from contextvars import ContextVar

# Context variable for request ID - accessible from any async context
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Width for the logger name field (for alignment)
LOGGER_NAME_WIDTH = 40


def abbreviate_logger_name(name: str) -> str:
    """
    Abbreviate logger name for cleaner output.

    Examples:
        iris.pipeline.chat.course_chat_pipeline -> i.p.chat.course_chat_pipeline
        iris.llm.request_handler -> i.llm.request_handler
        uvicorn.access -> uvicorn.access
    """
    abbreviations = [
        ("iris.", "i."),
        ("pipeline.", "p."),
    ]
    result = name
    for full, short in abbreviations:
        result = result.replace(full, short)
    return result


class HealthCheckFilter(logging.Filter):
    """
    Filter out health check endpoint logs from uvicorn.access.

    Health checks are called frequently and flood the logs with noise.
    """

    EXCLUDED_PATHS = {"/api/v1/health/", "/api/v1/health", "/health", "/health/"}

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to suppress the log record, True to allow it."""
        message = record.getMessage()
        # Check if any excluded path appears in the log message
        for path in self.EXCLUDED_PATHS:
            if path in message:
                return False
        return True


class IrisFormatter(logging.Formatter):
    """
    Custom log formatter for Iris with:
    - Abbreviated logger names
    - Fixed-width logger name field for alignment
    - Request ID from context variable
    - Colored log levels
    - Clean, scannable format
    """

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"

    # Prefix for continuation lines (aligns with message start)
    # Format: "YYYY-MM-DD HH:MM:SS.mmm | LEVEL | [reqid___] logger_name... | "
    # Length: 23 + 3 + 5 + 3 + 10 + 1 + 40 + 3 = 88 chars
    CONTINUATION_PREFIX = " " * 88

    def format(self, record: logging.LogRecord) -> str:
        # Get request ID from context (padded to 8 chars for alignment)
        request_id = request_id_var.get()[:8].ljust(8)

        # Abbreviate and pad logger name
        abbreviated_name = abbreviate_logger_name(record.name)
        padded_name = abbreviated_name[:LOGGER_NAME_WIDTH].ljust(LOGGER_NAME_WIDTH)

        # Format timestamp
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        milliseconds = int(record.msecs)
        timestamp_with_ms = f"{timestamp}.{milliseconds:03d}"

        # Format level with color (padded to 5 chars)
        level_name = record.levelname[:5].ljust(5)
        color = self.COLORS.get(record.levelname, "")
        colored_level = f"{color}{level_name}{self.RESET}" if color else level_name

        # Build the log line
        message = record.getMessage()

        # Handle multiline messages - indent continuation lines
        if "\n" in message:
            lines = message.split("\n")
            message = (
                lines[0]
                + "\n"
                + "\n".join(self.CONTINUATION_PREFIX + line for line in lines[1:])
            )

        # Handle exceptions
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        log_line = f"{timestamp_with_ms} | {colored_level} | [{request_id}] {padded_name} | {message}"

        # Indent exception traceback lines
        if record.exc_text:
            indented_exc = "\n".join(
                self.CONTINUATION_PREFIX + line for line in record.exc_text.split("\n")
            )
            log_line = f"{log_line}\n{indented_exc}"

        return log_line


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging for the entire application.

    Should be called once at application startup.

    Args:
        level: The log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Create console handler with our custom formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(IrisFormatter())

    # Set the level
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(log_level)
    console_handler.setLevel(log_level)

    # Add handler to root logger
    root_logger.addHandler(console_handler)

    # Suppress noisy third-party loggers
    noisy_loggers = [
        "langfuse",
        "httpcore",
        "httpx",
        "openai",
        "urllib3",
        "asyncio",
        "apscheduler",
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Configure uvicorn loggers to use our format
    for uvicorn_logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.addHandler(console_handler)
        uvicorn_logger.propagate = False

    # Add filter to suppress health check logs from uvicorn.access
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(HealthCheckFilter())


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    This is a convenience wrapper around logging.getLogger that ensures
    consistency across the codebase.

    Args:
        name: Logger name (typically __name__)

    Returns:
        A configured logger instance
    """
    return logging.getLogger(name)


def set_request_id(request_id: str) -> None:
    """
    Set the request ID for the current context.

    Args:
        request_id: The request ID to set
    """
    request_id_var.set(request_id)


def get_request_id() -> str:
    """
    Get the current request ID.

    Returns:
        The current request ID or "-" if not set
    """
    return request_id_var.get()


def generate_request_id() -> str:
    """
    Generate a short unique request ID.

    Returns:
        An 8-character hex string
    """
    return secrets.token_hex(4)
