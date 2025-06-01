"""Logging utilities for solution repository creation."""

import logging
import sys
from typing import Optional, Dict, Any


def setup_logger(name: str, level: str = "INFO", format_string: Optional[str] = None) -> logging.Logger:
    """Set up a logger with the specified configuration.
    
    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string for log messages
        
    Returns:
        Configured logger instance
    """
    # TODO: Implement logger setup
    # - Create logger with specified name
    # - Set logging level
    # - Configure formatter
    # - Add console handler
    # - Return configured logger
    return logging.getLogger(name)


def get_solution_logger(step: str) -> logging.Logger:
    """Get a logger for a specific solution creation step.
    
    Args:
        step: Solution creation step name
        
    Returns:
        Logger instance for the step
    """
    # TODO: Implement step-specific logger
    # - Create logger with step-specific name
    # - Apply step-specific configuration
    # - Return logger
    return logging.getLogger(f"solution.{step}")


def log_phase_start(logger: logging.Logger, phase: str) -> None:
    """Log the start of a solution creation phase.
    
    Args:
        logger: Logger instance
        phase: Phase name
    """
    # TODO: Implement phase start logging
    logger.info(f"Starting phase: {phase}")


def log_phase_end(logger: logging.Logger, phase: str, success: bool) -> None:
    """Log the end of a solution creation phase.
    
    Args:
        logger: Logger instance
        phase: Phase name
        success: Whether the phase completed successfully
    """
    # TODO: Implement phase end logging
    status = "successfully" if success else "with errors"
    logger.info(f"Completed phase: {phase} {status}")


def log_error_with_context(logger: logging.Logger, error: Exception, context: Dict[str, Any]) -> None:
    """Log an error with additional context information.
    
    Args:
        logger: Logger instance
        error: Exception that occurred
        context: Additional context information
    """
    # TODO: Implement error logging with context
    logger.error(f"Error: {str(error)}, Context: {context}") 