# Step 3 Solution Repository Creator - Test Suite

This directory contains comprehensive unit tests for the Step 3 Solution Repository Creator, focusing on Python language support.

## 🚀 Quick Start

### Using the Test Runner (Recommended)

```bash
# Run all tests
python run_all_tests.py

# Run with coverage
python run_all_tests.py --coverage

# Run in parallel (faster)
python run_all_tests.py --parallel

# Run specific files
python run_all_tests.py --files conftest.py

# Filter by pattern
python run_all_tests.py --pattern "test_"

# List available tests
python run_all_tests.py --list

# Check dependencies
python run_all_tests.py --check-deps
```

### Using pytest directly

```bash
# From the project root (edutelligence/)
cd ../../../../../
python -m pytest hyperion/app/creation_steps/step3_create_solution_repository/tests/

# Or set PYTHONPATH and run from tests directory
export PYTHONPATH=/path/to/edutelligence
pytest
```

## 📋 Available Test Files

- `conftest.py` - Pytest configuration and fixtures
- `run_all_tests.py` - Comprehensive test runner

## 🔧 Dependencies

### Required
- `pytest` - Testing framework

### Optional (for enhanced features)
- `pytest-asyncio` - Async test support
- `pytest-cov` - Coverage reporting
- `pytest-xdist` - Parallel test execution

Install dependencies:
```bash
pip install pytest pytest-asyncio pytest-cov pytest-xdist
```

## 🧪 Features

- **Mock fixtures** for AI models and test data
- **Flexible imports** that work with or without actual dependencies
- **Path resolution** that works from any directory
- **Coverage reporting** with HTML and XML output
- **Parallel execution** for faster testing

## 🚨 Troubleshooting

If you get import errors:
1. Use the test runner: `python run_all_tests.py`
2. Or run from project root with proper PYTHONPATH
3. Check dependencies: `python run_all_tests.py --check-deps`
