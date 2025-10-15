.. _test_structure:

=====================
Test Structure Overview
=====================

The Athena testing framework is organized in a hierarchical structure that mirrors the module architecture while providing comprehensive test coverage for both isolated unit tests and integration tests.

Directory Structure
====================

The tests are organized under ``athena/tests/`` with the following structure:

.. code-block:: text

    athena/tests/
    ├── pyproject.toml              # Test dependencies and configuration
    ├── poetry.lock                 # Locked dependency versions
    ├── poetry.toml                 # Poetry configuration
    └── modules/                    # Module-specific tests
        ├── text/                   # Text module tests
        │   ├── module_text_llm/    # Text LLM module tests
        │   │   ├── mock/           # Mock tests (no API calls)
        │   │   │   ├── conftest.py
        │   │   │   ├── test_default_approach_mock.py
        │   │   │   └── utils/      # Mock utilities
        │   │   │       ├── mock_config.py
        │   │   │       ├── mock_env.py
        │   │   │       ├── mock_llm.py
        │   │   │       └── mock_openai.py
        │   │   └── real/           # Real tests (with API calls)
        │   │       ├── conftest.py
        │   │       ├── test_default_approach_real.py
        │   │       └── data/       # Test data
        │   │           └── exercises/
        │   │               ├── exercise-6715.json
        │   │               ├── exercise-6787.json
        │   │               ├── exercise-6794.json
        │   │               ├── exercise-6911.json
        │   │               └── exercise-7195.json
        │   └── utils/              # Shared text module utilities
        │       ├── mock_config.py
        │       ├── mock_env.py
        │       ├── mock_llm_config.py
        │       ├── mock_llm.py
        │       └── mock_openai.py
        ├── programming/             # Programming module tests
        │   └── module_programming_llm/
        │       └── mock/            # Mock tests only
        │           ├── conftest.py
        │           ├── test_mock.py
        │           └── utils/       # Mock utilities
        │               ├── mock_config.py
        │               ├── mock_env.py
        │               ├── mock_llm.py
        │               ├── mock_module_config.py
        │               └── mock_openai.py
        └── modeling/                # Modeling module tests
            └── module_modeling_llm/
                ├── mock/            # Mock tests
                │   ├── conftest.py
                │   ├── test_basic_approach_mock.py
                │   └── utils/       # Mock utilities
                │       ├── mock_config.py
                │       ├── mock_llm_config.py
                │       ├── mock_llm.py
                │       └── mock_openai.py
                └── real/            # Real tests
                    ├── conftest.py
                    ├── test_real.py
                    ├── data/        # Test data
                    │   └── exercises/
                    │       ├── exercise-14676.json
                    │       └── exercise-15949.json
                    └── test_data/   # Additional test data
                        ├── ecommerce_data.py
                        └── hospital_data.py

Test Organization Principles
============================

1. **Module-Based Organization**: Each module has its own test directory under ``modules/{module_type}/module_{module_name}/``

2. **Mock vs Real Separation**: Tests are clearly separated into:
   - ``mock/``: Unit tests that don't make external API calls
   - ``real/``: Integration tests that use real APIs and services

3. **Shared Utilities**: Common testing utilities are placed in ``utils/`` directories at appropriate levels

4. **Test Data Management**: Real test data is stored in ``data/`` directories within ``real/`` test folders

5. **Configuration Files**: Each test directory has its own ``conftest.py`` for pytest fixtures and configuration

Key Components
==============

**pyproject.toml**
   The main configuration file for the test environment, including:

   - Test dependencies (pytest, pytest-asyncio, etc.)
   - Module dependencies with local development paths
   - Pytest configuration for async testing

**conftest.py files**
   Provide pytest fixtures and configuration for each test scope:

   - Session-level fixtures for environment setup
   - Module-specific fixtures for mock objects and configurations
   - Test data fixtures for consistent test execution

**Mock Utilities**
   Located in ``utils/`` directories, providing:

   - Mock LLM configurations and responses
   - Mock environment variables
   - Mock API clients and responses
   - Reusable test configurations

**Test Data**
   Exercise data stored as JSON files:

   - Exercise definitions with problem statements
   - Student submissions with various quality levels
   - Expected feedback and grading criteria
   - Metadata for test execution context

This structure ensures comprehensive test coverage while maintaining clear separation between different types of tests and providing reusable components for efficient test development.
