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
    path_env = os.environ["PATH"]
    for module in modules:
        # Check if test directory exists
        test_dir = f"tests/{module}"
        if not os.path.exists(test_dir):
            print(f"No tests found for {module}, skipping...")
            continue
        # Get the module's virtual environment
        venv_path = os.path.join(os.getcwd(), module, ".venv")
        if not os.path.exists(venv_path):
            print(f"Virtual environment not found for {module} at {venv_path}")
            continue
        # Set environment variables for the virtual environment
        os.environ["VIRTUAL_ENV"] = venv_path
        os.environ["PATH"] = os.path.join(venv_path, "bin") + os.pathsep + path_env
        python_path = os.path.join(venv_path, "bin", "python")
        pip_path = os.path.join(venv_path, "bin", "pip")
        print(f"Using Python path: {python_path}")

        try:
            # Install pytest in the virtual environment
            print(f"Installing pytest for {module}...")
            subprocess.run([pip_path, "install", "pytest"], check=True, capture_output=True, text=True)
            # Install pytest and pytest-asyncio in the virtual environment
            print(f"Installing pytest and pytest-asyncio for {module}...")
            subprocess.run([pip_path, "install", "pytest", "pytest-asyncio"], check=True, capture_output=True, text=True)

            # Run pytest using the module's virtual environment
            result = subprocess.run([python_path, "-m", "pytest", test_dir], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Tests failed for {module}:")
                print(result.stdout)
                print(result.stderr)
                success = False
            # Run pytest using the module's virtual environment, only running tests from mock directories
            mock_test_dir = os.path.join(test_dir, "mock")
            if os.path.exists(mock_test_dir):
                print(f"\nRunning tests for {module}...")
                result = subprocess.run([python_path, "-m", "pytest", mock_test_dir, "-v"], check=False)
                if result.returncode != 0:
                    print(f"\nTests failed for {module}")
                    success = False
                else:
                    print(f"\nTests passed for {module}")
            else:
                print(f"Tests passed for {module}")
                print(f"No mock tests found for {module}, skipping...")
        except Exception as e:
            print(f"Error running tests for {module}: {str(e)}")
            success = False
    if success:
        sys.exit(0)
    else:
        sys.exit(-1)
if __name__ == "__main__":
    main()
    