"""Iris Response Service: returns the answer of Iris to the last student message of a test case.

For now a stub returns a fixed answer. A later implementation will send the test case to a
running Pyris instance (as a ChatPipelineExecutionDTO) and collect the answer from the callback.
"""

from typing import Protocol

from ..evaluation_pipeline.models import TestCase


class IrisResponseService(Protocol):
    def get_response(self, test_case: TestCase) -> str: ...


class StubIrisResponseService:
    """Answers every test case with the same text, without calling Iris."""

    def get_response(self, test_case: TestCase) -> str:
        return (
            "This is a stub answer. Which part of the problem have you already tried, "
            "and what happened when you ran your code?"
        )
