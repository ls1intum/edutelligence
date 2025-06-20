# **AtlasML**

A lightweight FastAPI application template that supports **Conda** for environment management and **Poetry** for dependency management. This app provides a basic health check endpoint and is ready for development and testing.

---

## **Features**

- FastAPI framework for building APIs.
- Poetry for modern Python dependency management.
- Conda environment for isolating Python runtime and libraries.
- Pre-configured endpoints:
  - `/` - Home route.
  - `/health` - Health check.

---

## **Setup Instructions**

### 1. **Clone the Repository**

```bash
git clone <repository_url>
cd AtlasML
```

### 2. Setup Environment

1. Ensure you have [Conda](https://docs.anaconda.com/miniconda/install/#quick-command-line-install) and [Poetry](https://python-poetry.org/docs/#installation) installed on your system.

2. Install the dependencies:

```bash
poetry install
```

3. Activate the Virtual Environment:

```bash
poetry shell
```

4. Run the Application:

```bash
poetry run uvicorn atlasml.app:app --reload
```

5. Run the Tests

```bash
poetry run pytest -v
```

6. Lint the code

```bash
poetry run ruff check .
poetry run black .
```

## Environment Variables

Please create a `.env` file in the root directory and add the the environment variables according to the `.env.example` file. If you add new environment variables, please update the `.env.example` file.

## License
