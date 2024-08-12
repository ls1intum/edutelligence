import subprocess
import os
import sys


def main():
    modules = [
        "log_viewer",
        "assessment_module_manager",
        "athena",  # the version in this commit only, can differ for modules
        "modules/programming/module_example",
        "modules/programming/module_programming_llm",
        "modules/text/module_text_llm",
        "modules/text/module_text_cofee",
        "modules/programming/module_programming_themisml",
        "modules/modeling/module_modeling_llm",
        # "module_programming_apted" skip due to an error
    ]

    success = True

    for module in modules:
        if os.path.isdir(module):
            venv_path = os.path.join(os.getcwd(), module, ".venv")

            os.environ['VIRTUAL_ENV'] = venv_path
            os.environ['PATH'] = os.path.join(venv_path, "bin") + ":" + os.environ['PATH']

            result = subprocess.run(["poetry", "run", "prospector", "--profile",
                                     os.path.abspath(os.path.join(os.path.dirname(__file__), "../.prospector.yaml"))],
                                    cwd=module)
            if result.returncode != 0:
                success = False

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
