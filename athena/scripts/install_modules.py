import subprocess
import os
import sys


def main():
    modules = [
        "assessment_module_manager",
        "athena",
        "log_viewer",
        "modules/module_example",
        "modules/programming/module_programming_llm",
        "modules/text/module_text_llm",
        "modules/text/module_text_cofee",
        "modules/programming/module_programming_themisml",
        "modules/programming/module_programming_apted",
        "modules/modeling/module_modeling_llm",
    ]

    success = True

    for module in modules:
        if os.path.isdir(module):
            result = subprocess.run(["poetry", "install"], cwd=module)
            if result.returncode != 0:
                success = False

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
