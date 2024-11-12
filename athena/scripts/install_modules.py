import subprocess
import os
import sys


def main():
    modules = [
        "assessment_module_manager",
        "athena",
        "log_viewer",
        "modules/programming/module_example",
        "modules/programming/module_programming_llm",
        "modules/text/module_text_llm",
        "modules/text/module_text_cofee",
        "modules/programming/module_programming_themisml",
        "modules/programming/module_programming_apted",
        "modules/modeling/module_modeling_llm",
        "tests/integration_tests"
    ]

    success = True
    path_env = os.environ["PATH"]

    for module in modules:
        if os.path.isdir(module):

            path = os.path.join(os.getcwd(), module, ".venv")
            os.environ["VIRTUAL_ENV"] = path
            os.environ["PATH"] = os.path.join(path, "bin") + os.pathsep + path_env

            subprocess.run([sys.executable, "-m", "venv", path])
            result = subprocess.run(["poetry", "install"], cwd=path)

            if result.returncode != 0:
                success = False

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
