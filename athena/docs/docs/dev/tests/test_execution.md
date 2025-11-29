<div id="test_execution">

|                      |
|----------------------|
| Test Execution Guide |

</div>

This guide covers all methods for running Athena tests, from individual
module tests to comprehensive test suites.

# Running Tests Overview

Athena provides multiple ways to execute tests depending on your needs:

1.  **Mock Tests Only** (Default): Fast, isolated unit tests
2.  **Real Tests**: Integration tests with actual API calls
3.  **Individual Module Tests**: Targeted testing of specific modules
4.  **All Tests**: Comprehensive test suite execution

**Python and Poetry Setup**: Ensure you have completed the
`setup_install` guide

# Test Execution Methods

## Method 1: Centralized Test Execution

From the `athena/tests/` directory:

**Mock Tests Only**

``` bash
cd athena/tests
poetry run test_all
```

**Include Real Tests**

``` bash
cd athena/tests
poetry run test_all --include-real
```

**Note**: The `test_all` command is a short way for executing the script
`test_modules.py` from `athena/scripts/` directory.

## Method 2: Individual Module Testing

For targeted testing of specific modules, navigate to the module
directory and use its virtual environment. Here are examples for
`module_text_llm`, for other modules,proceed analogously:

**Text Module Testing**

``` bash
# Navigate to the text module
cd athena/modules/text/module_text_llm

# Activate the module's virtual environment
source .venv/bin/activate

# Run mock tests
pytest ../../../tests/modules/text/module_text_llm/mock/

# Run real tests (requires API configuration, explained below)
pytest ../../../tests/modules/text/module_text_llm/real/
```

# Test Configuration

## Environment Setup

**For Mock Tests**: No additional setup required beyond installing
dependencies.

**For Real Tests**: Requires proper API configuration:

For each module - `module_text_llm`, `module_modeing_llm` or
`module_programming_llm` - you need to set the following environment
variables by coping the `.env` file to `.env.example`:

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `OPENAI_API_VERSION`

# Test Data Management

## Real Test Data

Real tests use exercise data stored in JSON format:

**Location**:
`athena/tests/modules/{module_type}/module_{module_name}/real/data/exercises/`

**Format**: Each exercise file contains:

- Exercise metadata (id, title, type, max_points)
- Problem statement and grading instructions
- Student submissions with various quality levels
- Expected feedback and grading criteria

**Usage**: Tests load this data to create realistic test scenarios
without requiring live LMS data.

## Mock Test Data

Mock tests use programmatically generated test data:

> - **Location**: Defined in test files and utility modules
> - **Purpose**: Fast, deterministic testing without external
>   dependencies
> - **Examples**: Mock submissions, mock feedback, mock LLM responses

# Troubleshooting

Common Issues and Solutions:

**Import Errors**

- Ensure you're using the correct virtual environment
- Check that all dependencies are installed with `poetry install`

**API Configuration Errors**

- Verify environment variables are set correctly
- Check API key permissions and quotas
- Ensure network connectivity for real tests

**Test Data Issues**

- Verify JSON files are valid and properly formatted
- Check file paths and permissions
- Ensure test data matches expected schema
