# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resouce management, policy-based model selection, scheduling, and monitoring.

## Setup

### Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

### Installation

#### Poetry

Install Poetry, if you haven't already:

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

### Configuration

Logos maintains an own database to store information about services and models.

## Running the Service
Run the following command in your terminal after installation: 

```bash
poetry run uvicorn logos.main:app
```

Now you can use Logos as a basic proxy for your requests. To do this, you have to change two things
in your existing applications:
1. Change the URL to the URL of Logos

and, if you want to use Logos-Features:
2. Create a Logos-API-Key, a User, and a Profile containing LLM-API-Keys

If you don't provide a Logos-API-Key and instead provide an OpenAI-Key, your requests will
be immediately forwarded to OpenAI. This just serves for proxy purposes for now.

The provider enlisted for the LLM-Keys in the profiles can be set by the "provider"-Parameter in
the request header. If not given, OpenAI is used.
