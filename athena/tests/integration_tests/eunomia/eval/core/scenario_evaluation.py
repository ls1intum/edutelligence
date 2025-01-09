from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from eval.core.test_case_runner import run_test_case
from eval.models.entities.scenario import Scenario
from eval.models.entities.test_case_result import TestCaseResult
from eval.models.entities.scenario_result import ScenarioResult

def evaluate_scenario(scenario: Scenario) -> ScenarioResult:
    evaluation_results: List[TestCaseResult] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_test_case = {
            executor.submit(run_test_case, scenario, tc, i, 2, 5): tc
            for i, tc in enumerate(scenario.test_cases)
        }

        for future in as_completed(future_to_test_case):
            tc = future_to_test_case[future]
            result = future.result()
            if result is None:
                scenario.failed_tests_due_to_server.append(tc.name)
            else:
                evaluation_results.append(result)

    scenario_result = ScenarioResult(evaluation_results)
    return scenario_result