#!/usr/bin/env python3
"""
Comprehensive test runner for Step 3 solution repository creator tests.

This script runs all tests in the test folder with various options:
- Basic test execution
- Coverage reporting
- Parallel execution
- Specific test filtering
- Output formatting
"""

import sys
import subprocess
import argparse
import time
import os
from pathlib import Path
from typing import List, Optional


class TestRunner:
    """Test runner for Step 3 tests."""
    
    def __init__(self, test_dir: Path):
        self.test_dir = test_dir
        self.project_root = test_dir.parent.parent.parent.parent.parent  # Go up to edutelligence root
        self.start_time = None
        
    def run_all_tests(self, 
                     verbose: bool = True,
                     coverage: bool = False,
                     parallel: bool = False,
                     stop_on_first_failure: bool = False,
                     pattern: Optional[str] = None) -> int:
        """
        Run all tests with specified options.
        
        Args:
            verbose: Enable verbose output
            coverage: Generate coverage report
            parallel: Run tests in parallel
            stop_on_first_failure: Stop on first test failure
            pattern: Filter tests by pattern
            
        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        self.start_time = time.time()
        
        # Build pytest command
        cmd = self._build_pytest_command(
            verbose=verbose,
            coverage=coverage,
            parallel=parallel,
            stop_on_first_failure=stop_on_first_failure,
            pattern=pattern
        )
        
        # Print header
        self._print_header(cmd)
        
        try:
            # Set up environment
            env = os.environ.copy()
            env['PYTHONPATH'] = str(self.project_root)
            
            # Run tests from project root
            result = subprocess.run(cmd, cwd=self.project_root, env=env)
            
            # Print results
            self._print_results(result.returncode)
            
            return result.returncode
            
        except KeyboardInterrupt:
            print("\n❌ Tests interrupted by user")
            return 1
        except Exception as e:
            print(f"\n❌ Error running tests: {e}")
            return 1
    
    def run_specific_tests(self, test_files: List[str], verbose: bool = True) -> int:
        """
        Run specific test files.
        
        Args:
            test_files: List of test file names
            verbose: Enable verbose output
            
        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        self.start_time = time.time()
        
        # Validate test files exist
        missing_files = []
        valid_files = []
        
        for test_file in test_files:
            test_path = self.test_dir / test_file
            if test_path.exists():
                # Use relative path from project root
                relative_path = test_path.relative_to(self.project_root)
                valid_files.append(str(relative_path))
            else:
                missing_files.append(test_file)
        
        if missing_files:
            print(f"❌ Test files not found: {', '.join(missing_files)}")
            return 1
        
        if not valid_files:
            print("❌ No valid test files specified")
            return 1
        
        # Build command for specific files
        cmd = [sys.executable, "-m", "pytest"] + valid_files
        if verbose:
            cmd.extend(["-v", "--tb=short", "--color=yes"])
        
        self._print_header(cmd)
        
        try:
            # Set up environment
            env = os.environ.copy()
            env['PYTHONPATH'] = str(self.project_root)
            
            result = subprocess.run(cmd, cwd=self.project_root, env=env)
            self._print_results(result.returncode)
            return result.returncode
        except Exception as e:
            print(f"\n❌ Error running tests: {e}")
            return 1
    
    def list_available_tests(self) -> None:
        """List all available test files."""
        print("📋 Available test files:")
        print("-" * 50)
        
        test_files = sorted(self.test_dir.glob("test_*.py"))
        phase_test_files = sorted(self.test_dir.glob("*/test_*.py"))
        
        if test_files:
            print("Main test files:")
            for test_file in test_files:
                print(f"  • {test_file.name}")
        
        if phase_test_files:
            print("\nPhase-specific test files:")
            for test_file in phase_test_files:
                relative_path = test_file.relative_to(self.test_dir)
                print(f"  • {relative_path}")
        
        if not test_files and not phase_test_files:
            print("  No test files found")
        
        print()
    
    def check_test_dependencies(self) -> bool:
        """Check if required test dependencies are available."""
        print("🔍 Checking test dependencies...")
        
        required_packages = ["pytest"]
        optional_packages = ["pytest-asyncio", "pytest-cov", "pytest-xdist"]
        
        missing_required = []
        missing_optional = []
        
        for package in required_packages:
            if not self._check_package(package):
                missing_required.append(package)
        
        for package in optional_packages:
            if not self._check_package(package):
                missing_optional.append(package)
        
        if missing_required:
            print(f"❌ Missing required packages: {', '.join(missing_required)}")
            print("Install with: pip install " + " ".join(missing_required))
            return False
        
        if missing_optional:
            print(f"⚠️  Missing optional packages: {', '.join(missing_optional)}")
            print("Install with: pip install " + " ".join(missing_optional))
        
        print("✅ All required dependencies available")
        return True
    
    def _build_pytest_command(self,
                             verbose: bool = True,
                             coverage: bool = False,
                             parallel: bool = False,
                             stop_on_first_failure: bool = False,
                             pattern: Optional[str] = None) -> List[str]:
        """Build pytest command with specified options."""
        # Use relative path from project root
        test_path_relative = self.test_dir.relative_to(self.project_root)
        cmd = [sys.executable, "-m", "pytest", str(test_path_relative)]
        
        # Basic options
        if verbose:
            cmd.extend(["-v", "--tb=short", "--color=yes"])
        
        if stop_on_first_failure:
            cmd.append("-x")
        
        # Coverage options
        if coverage:
            cmd.extend([
                "--cov=hyperion.app.creation_steps.step3_create_solution_repository",
                "--cov-report=html",
                "--cov-report=term-missing",
                "--cov-report=xml"
            ])
        
        # Parallel execution
        if parallel and self._check_package("pytest-xdist"):
            cmd.extend(["-n", "auto"])
        
        # Pattern filtering
        if pattern:
            cmd.extend(["-k", pattern])
        
        # Async support
        if self._check_package("pytest-asyncio"):
            cmd.append("--asyncio-mode=auto")
        
        return cmd
    
    def _check_package(self, package_name: str) -> bool:
        """Check if a package is installed."""
        try:
            __import__(package_name.replace("-", "_"))
            return True
        except ImportError:
            return False
    
    def _print_header(self, cmd: List[str]) -> None:
        """Print test execution header."""
        print("🧪 Step 3 Solution Repository Creator - Test Runner")
        print("=" * 60)
        print(f"📁 Test directory: {self.test_dir}")
        print(f"🏃 Working directory: {self.project_root}")
        print(f"⚡ Command: {' '.join(cmd)}")
        print("=" * 60)
        print()
    
    def _print_results(self, exit_code: int) -> None:
        """Print test execution results."""
        duration = time.time() - self.start_time if self.start_time else 0
        
        print()
        print("=" * 60)
        print(f"⏱️  Test execution completed in {duration:.2f} seconds")
        
        if exit_code == 0:
            print("✅ All tests passed successfully!")
        else:
            print(f"❌ Tests failed with exit code: {exit_code}")
        
        print("=" * 60)


def main():
    """Main entry point for the test runner."""
    parser = argparse.ArgumentParser(
        description="Run Step 3 solution repository creator tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_all_tests.py                          # Run all tests
  python run_all_tests.py --coverage               # Run with coverage
  python run_all_tests.py --parallel               # Run in parallel
  python run_all_tests.py --pattern "test_models"  # Filter by pattern
  python run_all_tests.py --files test_models.py   # Run specific files
  python run_all_tests.py --list                   # List available tests
  python run_all_tests.py --check-deps             # Check dependencies
        """
    )
    
    parser.add_argument(
        "--coverage", "-c",
        action="store_true",
        help="Generate coverage report"
    )
    
    parser.add_argument(
        "--parallel", "-p",
        action="store_true",
        help="Run tests in parallel (requires pytest-xdist)"
    )
    
    parser.add_argument(
        "--stop-on-failure", "-x",
        action="store_true",
        help="Stop on first test failure"
    )
    
    parser.add_argument(
        "--pattern", "-k",
        type=str,
        help="Filter tests by pattern"
    )
    
    parser.add_argument(
        "--files", "-f",
        nargs="+",
        help="Run specific test files"
    )
    
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available test files"
    )
    
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Check test dependencies"
    )
    
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Reduce output verbosity"
    )
    
    args = parser.parse_args()
    
    # Get test directory
    test_dir = Path(__file__).parent
    runner = TestRunner(test_dir)
    
    # Handle special commands
    if args.list:
        runner.list_available_tests()
        return 0
    
    if args.check_deps:
        success = runner.check_test_dependencies()
        return 0 if success else 1
    
    # Check dependencies before running tests
    if not runner.check_test_dependencies():
        return 1
    
    # Run specific files or all tests
    if args.files:
        exit_code = runner.run_specific_tests(
            test_files=args.files,
            verbose=not args.quiet
        )
    else:
        exit_code = runner.run_all_tests(
            verbose=not args.quiet,
            coverage=args.coverage,
            parallel=args.parallel,
            stop_on_first_failure=args.stop_on_failure,
            pattern=args.pattern
        )
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main()) 