import os
import json
from eval.models.entities.scenario import Scenario
from eval.models.entities.scenario_result import ScenarioResult
from eval.reporting.helpers.generate_scenario_dataframes import generate_scenario_dataframes

def write_file_scenario_json_report(scenario: Scenario, scenario_result: ScenarioResult) -> None:
    base_dir = scenario.get_results_base_dir()
    os.makedirs(base_dir, exist_ok=True)

    dfs = generate_scenario_dataframes(scenario, scenario_result)
    scenario_df = dfs["scenario_summary"]

    scenario_summary_dict = dict(zip(scenario_df["Metric"], scenario_df["Value"]))

    summary_file_path = os.path.join(base_dir, "scenario_results.json")
    with open(summary_file_path, "w", encoding="utf-8") as f:
        json.dump(scenario_summary_dict, f, indent=4)