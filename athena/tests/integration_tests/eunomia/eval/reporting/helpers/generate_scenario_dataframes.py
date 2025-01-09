import pandas as pd
from typing import Dict
from eval.models.entities.scenario_result import ScenarioResult
from eval.models.entities.scenario import Scenario


def generate_scenario_dataframes(
    scenario: Scenario,
    scenario_result: ScenarioResult
) -> Dict[str, pd.DataFrame]:
    """
    Generate DataFrames for scenario summary, test case results, and missed criteria,
    applying final column names and derived columns directly so minimal downstream
    transformation is required.
    """

    # Scenario-level summary metrics
    correct_count = sum(r.test_case_detected_correctly for r in scenario_result.evaluation_results)

    scenario_data = [
        ["Total Cases", scenario_result.total_cases],
        ["Fully Correct Cases", scenario_result.fully_correct],
        ["Score Matched Count", scenario_result.score_matched_count],
        ["Average Test Case Score", f"{scenario_result.average_test_case_score:.2f}"],
        ["Correctly Detected Test Cases / Total Cases", f"{correct_count} / {scenario_result.total_cases}"],
        ["Total Cost", f"{scenario_result.total_cost:.4f}"],
        ["Average Cost", f"{scenario_result.average_cost:.4f}"],
        ["Average Request Time (s)", f"{scenario_result.average_request_time:.4f}"]
    ]
    scenario_df = pd.DataFrame(scenario_data, columns=["Metric", "Value"])

    # Per-test-case DataFrame with final naming and derived columns
    test_case_rows = []

    for er in scenario_result.evaluation_results:
        cost_value = f"{er.case_costs.total_usage.total_cost:.4f}" if er.case_costs else "0.0000"

        test_case_rows.append({
            "Test Case": er.name,
            "Test Case Detected Correctly": "Yes" if er.test_case_detected_correctly else "No",
            "Test Case Score (%)": f"{er.test_case_score_percent:.2f}",
            "Expected Points": er.expected_score,
            "Total Returned Points": er.returned_score,
            "Cost": cost_value,
            "Request Time (s)": f"{er.request_time:.4f}"
        })

    test_case_df = pd.DataFrame(test_case_rows)

    # Add "Wrong < Points" and "Wrong > Points" columns directly
    wrong_less_list = []
    wrong_more_list = []
    for er in scenario_result.evaluation_results:
        wrong_less_list.append(er.instructions_wrong_less)
        wrong_more_list.append(er.instructions_wrong_more)

    test_case_df["Wrong < Points"] = wrong_less_list
    test_case_df["Wrong > Points"] = wrong_more_list

    # Aggregate missed criteria
    instr_to_crit = {}
    for c in scenario.criteria:
        for instr in c.structured_grading_instructions:
            instr_to_crit[instr.id] = c.id

    missed_criteria_counts = {}
    for instr_id, count in scenario_result.missed_instruction_counts.items():
        crit_id = instr_to_crit.get(instr_id)
        if crit_id is None:
            continue
        crit_text_id = scenario.criterion_id_to_textual_id.get(crit_id, str(crit_id))
        missed_criteria_counts[crit_text_id] = missed_criteria_counts.get(crit_text_id, 0) + count

    if missed_criteria_counts:
        missed_criteria_data = [
            [crit_text_id, total_count]
            for crit_text_id, total_count in missed_criteria_counts.items()
        ]
        missed_criteria_df = pd.DataFrame(missed_criteria_data, columns=["Criterion (Textual ID)", "Missed Count"])
    else:
        missed_criteria_df = pd.DataFrame(columns=["Criterion (Textual ID)", "Missed Count"])

    return {
        "scenario_summary": scenario_df,
        "test_case_results": test_case_df,
        "missed_criteria": missed_criteria_df
    }
