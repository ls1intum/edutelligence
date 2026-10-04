"""Fixtures for the tiers that need the compose stack.

The stack is *not* started here. It is brought up once — by a developer or by
the CI step — and the tests attach to it. A suite that owns the lifecycle pays
the build cost on every run and tears the evidence down at exactly the moment a
failure needs inspecting.

When the stack is absent the stack-marked tests skip with the command to start
it, rather than failing with a connection error.
"""

from __future__ import annotations

import pytest
from harness.clients.admin import AdminClient
from harness.stack import compose

STACK_HINT = "Stack not running. Start it with: python -m harness.stack.compose up"


def pytest_collection_modifyitems(config, items):
    """Mark everything under tests/node and tests/client as needing the stack."""
    for item in items:
        path = str(item.fspath)
        if "/tests/node/" in path or "/tests/client/" in path:
            item.add_marker(pytest.mark.stack)


@pytest.fixture(scope="session")
def stack():
    """The running stack, or a skip."""
    if not compose.is_up():
        pytest.skip(STACK_HINT)
    return compose


@pytest.fixture(scope="session")
def orchestrator_url(stack) -> str:
    return stack.ORCHESTRATOR_URL


@pytest.fixture(scope="session")
def admin_key(stack) -> str:
    return stack.ADMIN_KEY


@pytest.fixture(scope="session")
def developer_key(stack) -> str:
    """An ordinary key with no elevated role.

    The client tier uses this rather than the admin key so a privilege check
    that silently stops being enforced shows up as a test failure.
    """
    return stack.DEVELOPER_KEY


@pytest.fixture(scope="session")
def admin(orchestrator_url, admin_key):
    with AdminClient(orchestrator_url, admin_key) as client:
        yield client


@pytest.fixture(scope="session")
def nodes(stack, admin):
    """Every simulated worker node, once its session is live."""
    return stack.wait_for_nodes()
