"""Shared fixtures.

The launch path refuses to start a session whose model is not served
locally, and an unevaluated policy refuses everything — which is right in
production and useless in a unit test that never touches a database. So the
suite runs with a satisfied policy by default; the tests that are *about*
the policy build their own.
"""

from __future__ import annotations

import pytest
from app import controls, db, docker_engine, model_policy


@pytest.fixture(autouse=True)
def owned_session_rows(monkeypatch):
    """The launch re-reads its row before handing out a credential.

    Without a database that read cannot answer, and every launch test would
    abort at the boundary instead of exercising what it is about. Tests
    about losing the row set their own answer.
    """

    async def still_starting(_session_id: int) -> bool:
        return True

    monkeypatch.setattr(db, "session_is_starting", still_starting)


@pytest.fixture(autouse=True)
def local_model_policy(monkeypatch):
    policy = model_policy.ModelPolicy(
        local_models=frozenset({"local-model"}),
        offered=("local-model",),
        # The lane a capacity reading is taken on. An empty one means the
        # key reaches nothing, which fails closed — right in production,
        # and not what any of these tests are about.
        local_deployments=frozenset({("1", "1")}),
        ok=True,
        unknown=False,
        detail="test policy: one local model",
    )

    async def evaluated() -> model_policy.ModelPolicy:
        return policy

    # Both the remembered decision and the re-establishing call: a scheduler
    # pass re-reads the policy every time it admits, and without a database
    # that read would answer 'unknown' and stop every admission test. The
    # underlying `load` is left alone so its own tests still exercise it.
    monkeypatch.setattr(model_policy, "_current", policy)
    monkeypatch.setattr(model_policy, "refresh", evaluated)


@pytest.fixture(autouse=True)
def session_image_present(monkeypatch):
    """The launch checks for the session image before it starts anything.

    Unstubbed, that check asks whatever Docker daemon happens to be running
    on the machine the tests run on — so the suite passed or hung depending
    on whether the developer had Docker Desktop open, which is not a
    property of the code under test. The test that is about a missing image
    answers for itself.
    """

    async def present(_image: str) -> bool:
        return True

    monkeypatch.setattr(docker_engine, "image_present", present)


@pytest.fixture(autouse=True)
def unpaused_runner(monkeypatch):
    """No operator has touched the controls, unless a test says otherwise.

    The real reader runs — it is the code under test elsewhere — but against
    an answer that needs no database. Tests about the controls give their
    own `get_controls`.
    """

    async def untouched():
        return None

    monkeypatch.setattr(db, "get_controls", untouched)
    controls.forget()
    yield
    controls.forget()
