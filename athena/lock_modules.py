import subprocess
import os
import sys


def main():
    modules = [
        "assessment_module_manager",
        "athena",
        "log_viewer",
        "module_example",
        "module_programming_llm",
        "module_text_llm",
        "module_text_cofee",
        "module_programming_themisml",
        "module_programming_apted"
    ]

    success = True

    for module in modules:
        if os.path.isdir(module):
            print(f"Resolving lock file for {module}...")
            result = subprocess.run(["poetry", "lock"], cwd=module)
            if result.returncode != 0:
                print(f"Lock file resolving failed for {module}")
                success = False
            else:
                print(f"Lock file resolved successfully for {module}")
        else:
            print(f"Directory {module} does not exist. Skipping...")

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
