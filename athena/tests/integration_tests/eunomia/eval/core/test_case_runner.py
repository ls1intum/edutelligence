import json
import time
from typing import List, Tuple

from eval.models.schemas.external.feedback import ModelingFeedback
from eval.utils.request_feedback import request_feedback
from eval.models.entities.scenario import Scenario
from eval.models.entities.test_case_result import TestCaseResult
from eval.models.schemas.external.api_response import LLMUsage


def run_test_case(
    scenario: Scenario,
    test_case,
    index: int,
    max_retries: int = 2,
    retry_delay: int = 5
) -> TestCaseResult | None:
    """
    Attempt to run a single test case multiple times if failures occur (e.g., server issues).
    If after max_retries+1 attempts it still fails, return a failed EvaluationResult.
    """
    uml_model = _load_test_case_uml_model(test_case.file)
    payload = {
        "exercise": scenario.exercise.dict(),
        "submission": {
            "id": index,
            "exerciseId": scenario.exercise.id,
            "model": json.dumps(uml_model),
        }
    }

    for attempt in range(max_retries + 1):
        try:
            start_time = time.perf_counter()
            feedback, llm_usage = _attempt_request_feedback(scenario.server_url, payload)
            end_time = time.perf_counter()

            request_time = end_time - start_time

            return TestCaseResult(scenario, test_case, feedback, llm_usage, request_time)
        except Exception as e:
            if attempt < max_retries:
                print(f"Test case '{test_case.name}' failed with error: {e}. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"Test case '{test_case.name}' failed after {max_retries + 1} attempts. Skipping this test case.")
                return  None

    return None


def _attempt_request_feedback(server_url: str, payload: dict) -> Tuple[List[ModelingFeedback], LLMUsage]:
    """
    Attempt to request feedback from the server. Raises an exception if fails.
    """
    feedback, llm_usage = request_feedback(server_url, payload)
    return feedback, llm_usage

def _load_test_case_uml_model(file_path: str) -> dict:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data
