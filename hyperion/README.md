# Hyperion: AI-Driven Programming Exercise Creation Assistance

**Hyperion** is a microservice designed to bring AI-driven intelligence to Learning Management Systems (LMSs), such as [Artemis](https://github.com/ls1intum/Artemis). Inspired by the Titan of light and enlightenment, Hyperion illuminates the process of creating engaging, effective programming exercises. It assists instructors by refining problem statements, generating code stubs, and providing context-aware suggestions — all while integrating seamlessly with an LMS and CI build agents for validation.

## Setup

### Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

### Installation

#### Poetry

Install Peotry, if you haven't already:

```bash
pip install poetry
```

Ensure that you are using poetry version 2.0.0 or higher.

```bash
poetry --version
```

If you have poetry < 2.0.0 installed, please run

```bash
poetry self update
```

#### Dependencies

Activate the virtual environment and install the dependencies:

```bash
poetry env activate
poetry install
```

## Running the Service

### Development

```bash
poetry run fastapi dev
```

### Production

```bash
poetry run fastapi run
```

## Usage

After running the application, you can access the FastAPI API documentation at `http://127.0.0.1:8000/docs` or `http://127.0.0.1:8000/redoc`.

## Generate OpenAPI YAML

To generate the OpenAPI YAML file, run the following command:

```bash
poetry run openapi
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

## Version Bump

To bump the version of the project, run the following command:

```bash
poetry version <version>
```

Where `<version>` is one of the following:

- patch
- minor
- major
- prepatch
- preminor
- premajor
- prerelease
