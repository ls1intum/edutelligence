#!/usr/bin/env python3
"""
Test runner for Hyperion project.

This script provides a convenient way to run all tests in the project.
"""

import sys
import subprocess
from pathlib import Path


def run_tests():
    """Run all tests in the tests directory."""
    project_root = Path(__file__).parent
    tests_dir = project_root / "tests"

    if not tests_dir.exists():
        print("❌ Tests directory not found!")
        return 1

    print("🧪 Running Hyperion tests...")
    print(f"📁 Tests directory: {tests_dir}")

    # Run pytest with verbose output
    cmd = [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short"]

    try:
        result = subprocess.run(cmd, cwd=project_root)
        return result.returncode
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
