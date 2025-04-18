import os
import json
from pathlib import Path
from eval.models.entities.scenario import Scenario
from eval.models.entities.scenario_result import ScenarioResult

def write_file_test_case_json_report(scenario: Scenario, scenario_result: ScenarioResult) -> None:
    """
    Write the individual test case evaluation results as JSON files in the scenario's results directory.
    No DataFrame transformations were needed here, so no changes are required.
    """
    base_dir = scenario.get_results_base_dir()
    results_dir = os.path.join(base_dir, "test_cases")
    os.makedirs(results_dir, exist_ok=True)

    name_to_file_map = {tc.name: tc.file for tc in scenario.test_cases}

    for result in scenario_result.evaluation_results:
        test_case_file_path = name_to_file_map.get(result.name)
        if not test_case_file_path:
            continue
        test_case_file_name = Path(test_case_file_path).name
        result_file_path = os.path.join(results_dir, test_case_file_name)

        with open(result_file_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=4)
