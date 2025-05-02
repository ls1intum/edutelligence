import subprocess
import os
import sys


def main():
    modules = [
        "docs",
        "log_viewer",
        "assessment_module_manager",
        "athena",  # the version in this commit only, can differ for modules
        "modules/programming/module_example",
        "modules/programming/module_programming_llm",
        "modules/text/module_text_llm",
        "modules/text/module_text_cofee",
        "modules/programming/module_programming_themisml",
        "modules/programming/module_programming_apted",
        "modules/modeling/module_modeling_llm"
    ]

    success = True
    for module in modules:
            # Check if test directory exists
        test_dir = f"tests/{module}"
        if not os.path.exists(test_dir):
            print(f"No tests found for {module}, skipping...")
            continue

        try:
            # Run pytest for each module that has tests
            result = subprocess.run(["pytest", test_dir], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Tests failed for {module}:")
                print(result.stdout)
                print(result.stderr)
                success = False
            else:
                print(f"Tests passed for {module}")
        except Exception as e:
            print(f"Error running tests for {module}: {str(e)}")
            success = False

    if success:
            sys.exit(0)
    else:
            sys.exit(-1)


if __name__ == "__main__":
    main()
