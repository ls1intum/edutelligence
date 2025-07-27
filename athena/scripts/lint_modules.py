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
    path_env = os.environ["PATH"]

    for module in modules:
        if os.path.isdir(module):

            path = os.path.join(os.getcwd(), module, ".venv")
            os.environ["VIRTUAL_ENV"] = path
            os.environ["PATH"] = os.path.join(path, "bin") + os.pathsep + path_env

            # Install prospector in the module's poetry environment
            print(f"Installing prospector in {module}...")
            
            # First try to install prospector via pip
            install_result = subprocess.run(["poetry", "run", "pip", "install", "prospector"], cwd=module, capture_output=True)
            if install_result.returncode != 0:
                print(f"Warning: Failed to install prospector via pip in {module}: {install_result.stderr.decode()}")
                print(f"Trying to install via poetry...")
                
                # Try installing via poetry install (which will install dev dependencies)
                poetry_install_result = subprocess.run(["poetry", "install"], cwd=module, capture_output=True)
                if poetry_install_result.returncode != 0:
                    print(f"Warning: Failed to install dependencies in {module}: {poetry_install_result.stderr.decode()}")
                    print(f"Continuing anyway - prospector might already be available...")
                else:
                    print(f"✅ Successfully installed dependencies in {module}")
            
            # Don't fail the entire script for installation issues

            print(f"Running prospector in {module}...")
            result = subprocess.run(["poetry", "run", "prospector", "--profile",
                                     os.path.abspath(os.path.join(os.path.dirname(__file__), "../.prospector.yaml"))],
                                    cwd=module, capture_output=True)
            if result.returncode != 0:
                print(f"❌ Prospector failed in {module}: {result.stderr.decode()}")
                success = False
            else:
                print(f"✅ Prospector completed successfully in {module}")

    if success:
        print("🎉 All modules linted successfully!")
        sys.exit(0)
    else:
        print("❌ Some modules failed linting. Check the output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
