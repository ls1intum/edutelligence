import subprocess
import os
import sys


def main():
    modules = [
        "docs",
        "log_viewer",
        "assessment_module_manager",
        "athena",  # the version in this commit only, can differ for modules
        "module_example",
        "module_programming_llm",
        "module_text_llm",
        "module_text_cofee",
        "module_programming_themisml",
        "module_modeling_llm",
        #"module_programming_apted" skip due to an error
    ]

    success = True

    for module in modules:
        if os.path.isdir(module):
            result = subprocess.run(["poetry", "run", "prospector", "--profile", "../.prospector.yaml"], cwd=module)
            if result.returncode != 0:
                success = False

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
