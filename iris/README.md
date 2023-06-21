# Pyris
...

## With local environment
### Setup
- Install **[Poetry](https://python-poetry.org/)**
- Install packages: `poetry install`
- Activate the virtual environment: `poetry shell`
- Copy `application.example.yml` to `application.yml` and change necessary values

### Run server
- Run server: `uvicorn app.main:app --reload`
- Access API docs: `http://localhost:8000/docs`

### Run tests
- `pytest`

## With docker
- (optional) Install **[Task](https://taskfile.dev)**
- Build docker: `docker compose build` or `task build`
- Run server: `docker compose up -d` or `task up`
- Stop server: `docker compose down` or `task down`

Checkout `Taskfile.yml` for more idiomatic commands
