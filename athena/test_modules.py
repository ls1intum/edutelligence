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
        "module_programming_apted"
    ]

    success = True

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
