from eval.models.entities.scenario import Scenario
from eval.reporting.write_file_scenario_csv_report import write_file_scenario_csv_report
from eval.reporting.write_file_scenario_json_report import write_file_scenario_json_report
from eval.reporting.write_file_test_case_json_report import write_file_test_case_json_report
from eval.reporting.write_terminal_scenario_summary_report import write_terminal_scenario_summary_report
from eval.models.entities.scenario_result import ScenarioResult

def output_results(scenario: Scenario, scenario_result: ScenarioResult) -> None:
    """
    Output all scenario results
    """
    # Terminal
    write_terminal_scenario_summary_report(scenario, scenario_result)
    # Files
    write_file_scenario_csv_report(scenario, scenario_result)
    write_file_scenario_json_report(scenario, scenario_result)
    write_file_test_case_json_report(scenario, scenario_result)
