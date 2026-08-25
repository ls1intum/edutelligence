"""Tests that the application actually assembles.

The unit tests around capacity and the state machine never import `main`, so a
route declared in a way FastAPI rejects — a 204 with a response model, a
duplicated path — would pass every one of them and then crash on startup. These
tests import the app and inspect what it built.
"""

from __future__ import annotations

import pytest
from app import main
from fastapi.routing import APIRoute
from starlette.status import HTTP_204_NO_CONTENT


@pytest.fixture(scope="module")
def routes() -> list[APIRoute]:
    return [r for r in main.app.routes if isinstance(r, APIRoute)]


def test_app_imports_and_builds_its_routes(routes):
    # Importing `main` is itself the assertion: FastAPI validates every route
    # at decoration time, so an invalid one raises here rather than in prod.
    assert len(routes) > 10


def test_no_route_returns_a_body_with_204(routes):
    for route in routes:
        if route.status_code == HTTP_204_NO_CONTENT:
            assert route.response_model is None, (
                f"{route.path} returns 204 but declares a response model; " "FastAPI refuses to start the app"
            )


def test_every_route_has_a_unique_method_and_path(routes):
    seen: set[tuple[str, str]] = set()
    for route in routes:
        for method in route.methods or set():
            key = (method, route.path)
            assert key not in seen, f"duplicate route {method} {route.path}"
            seen.add(key)


def test_only_health_is_unauthenticated(routes):
    """Every route but the health check must require the operator role.

    A new endpoint added without the dependency would otherwise expose session
    control — including cancelling other people's work — to any caller.
    """
    open_paths = {"/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
    for route in routes:
        if route.path in open_paths:
            continue
        dependency_names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "require_agent_operator" in dependency_names, f"{route.path} does not require the operator role"


def test_openapi_schema_generates(routes):
    # Schema generation exercises every response model; a bad annotation shows
    # up here rather than the first time someone opens /docs.
    schema = main.app.openapi()
    assert schema["info"]["title"] == "Logos Agent Runner"
    assert "/sessions" in schema["paths"]
