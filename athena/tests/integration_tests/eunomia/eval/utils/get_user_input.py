import questionary

def get_user_input():
    # Prompt user for max tests or test files
    input_str = questionary.text(
        "Maximum number of test cases (integer), OR a comma-separated list of specific test file names (all):"
    ).ask()

    if not input_str.strip():
        # User pressed Enter with no input
        max_tests = None
        test_files = None
    else:
        # Try interpreting input as an integer
        try:
            max_tests = int(input_str.strip())
            test_files = None
        except ValueError:
            # Not an integer, treat as list of files
            test_files = [f.strip() for f in input_str.split(',') if f.strip()]
            max_tests = None

    # Prompt for run name
    run_name_input = questionary.text(
        "Run name (test case name):"
    ).ask()
    run_name = run_name_input.strip() if run_name_input.strip() else None

    return max_tests, test_files, run_name

