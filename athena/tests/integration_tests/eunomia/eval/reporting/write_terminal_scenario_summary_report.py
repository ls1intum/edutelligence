from rich.table import Table
from rich.console import Console
from rich import box

from eval.models.entities.scenario_result import ScenarioResult
from eval.models.entities.scenario import Scenario
from eval.reporting.helpers.generate_scenario_dataframes import generate_scenario_dataframes

def _create_rich_table_from_df(df, title: str) -> Table:
    table = Table(title=title, box=box.MINIMAL_DOUBLE_HEAD, show_lines=True)
    for col in df.columns:
        table.add_column(col, style="bold", no_wrap=True, justify="left", max_width=20, overflow="ellipsis")

    for _, row in df.iterrows():
        row_values = [str(v) for v in row.values]
        table.add_row(*row_values)
    return table

def _create_test_case_table(test_case_df) -> Table:
    table = Table(title="Per Test Case Results", box=box.MINIMAL_DOUBLE_HEAD, show_lines=True)
    for col in test_case_df.columns:
        table.add_column(col, style="bold", no_wrap=True, max_width=20, overflow="ellipsis", justify="left")

    for _, row in test_case_df.iterrows():
        row_values = []
        for col in test_case_df.columns:
            val = str(row[col])
            if col == "Test Case Detected Correctly":
                val = val.strip().lower()
                val = "[green]Yes[/]" if val == "yes" else "[red]No[/]"
            row_values.append(val)
        table.add_row(*row_values)

    return table

def write_terminal_scenario_summary_report(scenario: Scenario, scenario_result: ScenarioResult) -> None:
    """
    Print a scenario summary table and per-test-case results table to the terminal
    """
    dfs = generate_scenario_dataframes(scenario, scenario_result)
    scenario_df = dfs["scenario_summary"]
    test_case_df = dfs["test_case_results"]

    console = Console()
    test_case_table = _create_test_case_table(test_case_df)
    scenario_table = _create_rich_table_from_df(scenario_df, title="Scenario Summary")

    console.print(test_case_table)
    console.print(scenario_table)
