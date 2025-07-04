import subprocess
import os
import sys
import argparse
import shutil


def main():
    parser = argparse.ArgumentParser(description='Run tests for Athena modules')
    parser.add_argument('--include-real', action='store_true',
                      help='Include real tests in addition to mock tests')
    args = parser.parse_args()

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
    
    # Set up Python path to include parent directories for llm_core imports
    current_dir = os.getcwd()
    python_path_dirs = [
        current_dir,  # athena root
        os.path.join(current_dir, "llm_core"),  # llm_core module
    ]
    python_path = os.pathsep.join(python_path_dirs)
    os.environ["PYTHONPATH"] = python_path

    test_results_dir = "test-results"
    if os.path.exists(test_results_dir):
        shutil.rmtree(test_results_dir)
    os.makedirs(test_results_dir)

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
        python_path_exec = os.path.join(venv_path, "bin", "python")
        pip_path = os.path.join(venv_path, "bin", "pip")

        print(f"Using Python path: {python_path_exec}")

        try:
            # Install pytest and pytest-asyncio in the virtual environment
            print(f"Installing pytest and pytest-asyncio for {module}...")
            subprocess.run([pip_path, "install", "pytest", "pytest-asyncio"], check=True, capture_output=True, text=True)

            # Run pytest using the module's virtual environment, only running tests from mock directories
            mock_test_dir = os.path.join(test_dir, "mock")
            if os.path.exists(mock_test_dir):
                print(f"\nRunning mock tests for {module}...")
                junit_file = os.path.join(test_results_dir, f"{module.replace('/', '_')}_mock.xml")
                result = subprocess.run(
                    [python_path_exec, "-m", "pytest", mock_test_dir, "-v", f"--junitxml={junit_file}"],
                    check=False, env=dict(os.environ, PYTHONPATH=python_path))
                if result.returncode != 0:
                    print(f"\nMock tests failed for {module}")
                    success = False
                else:
                    print(f"\nMock tests passed for {module}")
            else:
                print(f"No mock tests found for {module}, skipping...")

            # Run real tests if requested and if module has real tests
            if args.include_real:
                real_test_dir = os.path.join(test_dir, "real")
                if os.path.exists(real_test_dir):
                    # Change to the module directory for real tests
                    module_dir = os.path.join(os.getcwd(), module)
                    if os.path.exists(module_dir):
                        original_dir = os.getcwd()
                        os.chdir(module_dir)
                        print(f"\nRunning real tests from {module_dir}...")
                        
                        # Use absolute path for JUnit XML output to write to top-level test-results/
                        junit_file_real = os.path.join(original_dir, test_results_dir, f"{module.replace('/', '_')}_real.xml")
                        # Run pytest with the real test directory as the test path
                        result = subprocess.run(
                            [python_path_exec, "-m", "pytest", '../../../' + real_test_dir, "-v", f"--junitxml={junit_file_real}"],
                            check=False, env=dict(os.environ, PYTHONPATH=python_path)
                        )
                        if result.returncode != 0:
                            print(f"\nReal tests failed for {module}")
                            success = False
                        else:
                            print(f"\nReal tests passed for {module}")
                        # Change back to original directory
                        os.chdir(original_dir)
                    else:
                        print(f"Module directory not found for {module}, skipping real tests...")
                else:
                    print(f"No real tests found for {module}, skipping...")

        except Exception as e:
            print(f"Error running tests for {module}: {str(e)}")
            success = False

    if success:
        sys.exit(0)
    else:
        sys.exit(-1)


if __name__ == "__main__":
    main()
