# Pyris
...

## Setup
- Install **[Poetry](https://python-poetry.org/)**
- Install packages: `poetry install`
- Activate the virtual environment: `poetry shell`
- Copy `.env.example` to `.env` and change necessary values

## Run server
- Run server: `uvicorn app.main:app --reload`
- Access API docs: `http://localhost:8000/docs`

## Run tests
- `pytest`
