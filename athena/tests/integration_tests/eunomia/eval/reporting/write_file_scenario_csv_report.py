import os
from eval.models.entities.scenario_result import ScenarioResult
from eval.models.entities.scenario import Scenario
from eval.reporting.helpers.generate_scenario_dataframes import generate_scenario_dataframes

def write_file_scenario_csv_report(scenario: Scenario, scenario_result: ScenarioResult) -> None:
    base_dir = scenario.get_results_base_dir()
    results_dir = os.path.join(base_dir, "tables")
    os.makedirs(results_dir, exist_ok=True)

    dfs = generate_scenario_dataframes(scenario, scenario_result)

    scenario_df = dfs["scenario_summary"]
    test_case_df = dfs["test_case_results"]

    scenario_df.to_csv(os.path.join(results_dir, "scenario_summary.csv"), index=False)
    test_case_df.to_csv(os.path.join(results_dir, "test_case_results.csv"), index=False)
