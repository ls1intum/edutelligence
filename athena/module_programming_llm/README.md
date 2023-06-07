# Module Programming LLM

This system implements an approach for (semi-)automated assessment of programming exercises.

It implements the approach described in the following master's thesis:
> **An LLM-Enabled Approach for Automated Feedback Generation on Programming Exercises**  
> Felix T.J. Dietrich

## Development Setup

1. Copy the `.env.example` file to `.env` and fill in the environment in `.env`:

```
cp .env.example .env
```

2. Install dependencies with poetry:

```
poetry install
```

## Usage

### Start Directly

`poetry run module`

### Start with Docker

`docker-compose up --build`

### Start with Docker in Production Mode

`docker-compose up --env-file .env.production --build`