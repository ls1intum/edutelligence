"""
Provides the experiment environment for Athena so it knows which experiment is currently running.

Note: This is mainly being used in the Playground during research and development but could also be used in production.
"""

import contextvars
from typing import Optional

from fastapi import Request
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class ExperimentEnvironment(BaseModel):
    experiment_id: Optional[str] = None
    module_configuration_id: Optional[str] = None
    run_id: Optional[str] = None


experiment_context: contextvars.ContextVar[ExperimentEnvironment] = contextvars.ContextVar("experiment")


class ExperimentMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle the experiment environment in the context of HTTP requests.

    This middleware allows to get the experiment environment context in each HTTP request.
    The context is then available throughout the processing of a request, even in asynchronous operations.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        """
        Middleware dispatcher.

        This method sets the experiment environment context at the start of processing each request.
        It then gets the response from the next middleware or the actual route handler, and returns it.

        Args:
            request (Request): The incoming HTTP request.
            call_next (RequestResponseEndpoint): The next middleware or route handler.

        Returns:
            The response from the next middleware or route handler.
        """
        experiment = ExperimentEnvironment(
            experiment_id=request.headers.get('X-Experiment-ID'), 
            module_configuration_id=request.headers.get('X-Module-Configuration-ID'),
            run_id=request.headers.get('X-Run-ID'),
        )

        experiment_context.set(experiment)
        response = await call_next(request)
        return response


def get_experiment_environment() -> ExperimentEnvironment:
    """
    Get the experiment environment.

    Returns:
        ExperimentEnvironment: The experiment environment
    """
    return experiment_context.get(ExperimentEnvironment(
            experiment_id=None, 
            module_configuration_id=None,
            run_id=None,
        )
    )
