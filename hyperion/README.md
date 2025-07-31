# Hyperion: AI-Driven Programming Exercise Creation Assistance

**Hyperion** is a microservice designed to bring AI-driven intelligence to Learning Management Systems (LMSs), such as [Artemis](https://github.com/ls1intum/Artemis). Inspired by the Titan of light and enlightenment, Hyperion illuminates the process of creating engaging, effective programming exercises. It assists instructors by refining problem statements, generating code stubs, and providing context-aware suggestions — all while integrating seamlessly with an LMS and CI build agents for validation.

## Features

Hyperion provides an 8-step workflow for creating programming exercises:

1. **Define Boundary Conditions** - Establish exercise constraints and requirements
2. **Draft Problem Statement** - Generate initial exercise descriptions
3. **Create Solution Repository** - Generate complete solution code
4. **Create Template Repository** - Generate starter code for students
5. **Create Test Repository** - Generate automated test cases
6. **Finalize Problem Statement** - Refine and polish exercise descriptions
7. **Configure Grading** - Set up automated grading criteria
8. **Review and Refine** - Check for inconsistencies and improve content

### Available Services

- **Inconsistency Checking**: Analyze exercises for conflicts between problem statements, solution code, template code, and tests
- **Problem Statement Rewriting**: Improve and refine exercise descriptions using AI

## Setup

### Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

### Installation

```bash
# Install Poetry
brew install poetry
```

#### Dependencies

Activate the virtual environment and install the dependencies:

```bash
poetry env activate
poetry install
```

## Running the Service

### Development with Docker (Recommended)

For hot reloading and the best development experience:

```bash
# Navigate to docker directory
cd docker

# Start Hyperion in development mode (omit -d to keep terminal attached)
docker compose -f compose.local.yaml up -d

# View logs
docker compose -f compose.local.yaml logs -f hyperion-dev

# Stop the service
docker compose -f compose.local.yaml down
```

### Direct Development

```bash
poetry run fastapi dev
```

### Production

```bash
poetry run fastapi run
```

## Configuration

Copy `.env.example` to `.env` and configure your AI provider:

```bash
cp .env.example .env
```

### Supported Providers

**OpenAI:**

```env
MODEL_NAME=gpt-4o-mini
OPENAI_API_KEY=your_openai_api_key_here
```

**Azure OpenAI:**

```env
MODEL_NAME=azure_openai:your-deployment-name
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_azure_api_key_here
OPENAI_API_VERSION=2024-02-15-preview
```

**Ollama (Local):**

```env
MODEL_NAME=ollama:llama3.1:8b
OLLAMA_HOST=http://localhost:11434
```

**OpenRouter:**

```env
MODEL_NAME=openrouter:meta-llama/llama-3.1-8b-instruct
OPENROUTER_API_KEY=sk-or-v1-your_api_key_here
```

**OpenWebUI:**

```env
MODEL_NAME=openwebui:deepseek-r1:70b
OPENWEBUI_BASE_URL=https://gpu.aet.cit.tum.de/ollama/
OPENWEBUI_API_KEY=sk-your-api-key-here
```

**Development Settings:**

```env
DISABLE_AUTH=true  # For development only
API_KEY=your-api-key  # For production
```

## Usage

After running the application, you can access the FastAPI API documentation at `http://127.0.0.1:8000/docs` or `http://127.0.0.1:8000/redoc`.

## Development

### Generate OpenAPI YAML

```bash
poetry run openapi
```

### Sync OpenAPI Spec with Artemis

```bash
poetry run sync-openapi-artemis
```

## Testing

Hyperion includes a comprehensive test suite organized in a global test directory structure.

### Running Tests

#### Run All Tests

```bash
# Using pytest directly
pytest tests/ -v

# Using the test runner script
python run_tests.py
```

#### Run Specific Test Modules

```bash
# Run step 3 integration tests
pytest tests/creation_steps/step3_create_solution_repository/step3_integration.py -v

# Run workspace tests
pytest tests/creation_steps/workspace/ -v

# Run specific test file
pytest tests/creation_steps/workspace/test_file_manager.py -v
```

#### Run Specific Test Cases

```bash
# Run a specific test class
pytest tests/creation_steps/step3_create_solution_repository/step3_integration.py::TestSolutionRepositoryCreatorIntegration -v

# Run a specific test method
pytest tests/creation_steps/workspace/test_file_manager.py::TestFileManager::test_write_file_success -v
```

#### Test Options

```bash
# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run with detailed output
pytest tests/ -v --tb=long

# Run tests in parallel (if pytest-xdist is installed)
pytest tests/ -n auto

# Run only failed tests from last run
pytest tests/ --lf
```

### Test Dependencies

The tests require additional dependencies that are included in the development group:

```bash
# Install test dependencies
poetry install --with dev

# Or install specific test packages
poetry add --group dev pytest pytest-asyncio pytest-cov
```

## Formatting

### Black

To format the code, run the following command:

```bash
poetry run black .
```

### Flake8

To lint the code, run the following command:

```bash
poetry run flake8 .
```

