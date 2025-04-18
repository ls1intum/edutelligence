from pathlib import Path
from typing import List, Optional

def filter_scenarios(
    scenarios,
    max_tests: Optional[int] = None,
    test_files: Optional[List[str]] = None
):
    """
    Filter scenarios based on max_tests and test_files.
    If test_files is provided, only test cases whose files match any in test_files are kept.
    If max_tests is provided, truncate the test cases to that number.
    """
    filtered = []
    for scenario in scenarios:
        # Filter by test files if provided
        if test_files is not None:
            scenario.test_cases = [
                tc for tc in scenario.test_cases
                if Path(tc.file).name in test_files
            ]
            if not scenario.test_cases:
                print(f"No test cases found matching {test_files} in scenario '{scenario.exercise.title}'. Skipping scenario.")
                continue

        # Limit number of test cases if max_tests is specified
        if max_tests is not None and max_tests < len(scenario.test_cases):
            scenario.test_cases = scenario.test_cases[:max_tests]

        filtered.append(scenario)

    return filtered