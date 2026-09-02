"""Shared fixtures.

The launch path refuses to start a session whose model is not served
locally, and an unevaluated policy refuses everything — which is right in
production and useless in a unit test that never touches a database. So the
suite runs with a satisfied policy by default; the tests that are *about*
the policy build their own.
"""

from __future__ import annotations

import pytest
from app import db, model_policy


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
