import subprocess
import os
import sys
import shutil


def main():
    poetry_path = shutil.which("poetry")
    if poetry_path is None:
        print("Could not find poetry.")
        sys.exit(1)
    os.environ["POETRY_PATH"] = poetry_path

    test_modules = [
        "tests/integration_tests"
    ]

    success = True

    for module in test_modules:
        result = subprocess.run([poetry_path, "run", "pytest", module])
        if result.returncode != 0:
            success = False

    sys.exit(0 if success else -1)


if __name__ == "__main__":
    main()
