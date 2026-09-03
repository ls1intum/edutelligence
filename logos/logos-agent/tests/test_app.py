"""Tests that the application actually assembles.

The unit tests around capacity and the state machine never import `main`, so a
route declared in a way FastAPI rejects — a 204 with a response model, a
duplicated path — would pass every one of them and then crash on startup. These
tests import the app and inspect what it built.
"""

from __future__ import annotations

from datetime import datetime, timezone

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


class TestScreenshotContainment:
    """What the screenshot route may hand out.

    The screenshots are written by the session itself, which runs
    unprivileged: it can leave a link named like a screenshot pointing at
    anything the runner can read — the runner's own /proc/self included.
    The route must serve only regular files inside the session's own
    artefact directory, verified without following links.
    """

    @staticmethod
    def _patch_root(monkeypatch, tmp_path):
        from dataclasses import replace

        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))

    @staticmethod
    async def _body(response) -> bytes:
        # A StreamingResponse's body_iterator is already async; iterating it
        # is what a client receives, so a response without a stream fails
        # loudly here instead of passing with an empty body.
        return b"".join([chunk async for chunk in response.body_iterator])

    async def test_a_regular_file_is_served(self, monkeypatch, tmp_path):
        from app.main import get_screenshot

        self._patch_root(monkeypatch, tmp_path)
        directory = tmp_path / "7" / "screenshots"
        directory.mkdir(parents=True)
        payload = b"\x89PNG fake bytes"
        (directory / "shot.png").write_bytes(payload)

        response = await get_screenshot(session_id=7, name="shot.png", _=None)

        assert response.status_code == 200
        assert response.media_type == "image/png"
        assert response.headers["content-length"] == str(len(payload))
        assert await self._body(response) == payload

    async def test_a_regular_file_is_streamed_over_the_asgi_layer(self, monkeypatch, tmp_path):
        # Through the real ASGI call path, not by iterating the attribute:
        # a plain Response object sent by that path carries only its
        # (empty) body — a route that "serves" a file that way would pass
        # any test that reads body_iterator by hand and still ship zero
        # bytes to the browser.
        import httpx
        from app.auth import require_agent_operator

        self._patch_root(monkeypatch, tmp_path)
        directory = tmp_path / "7" / "screenshots"
        directory.mkdir(parents=True)
        payload = b"\x89PNG real bytes for the asgi path"
        (directory / "shot.png").write_bytes(payload)

        main.app.dependency_overrides[require_agent_operator] = lambda: None
        try:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/sessions/7/screenshots/shot.png")
        finally:
            main.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["content-length"] == str(len(payload))
        assert response.content == payload

    async def test_a_symlinked_screenshots_directory_is_not_followed(self, monkeypatch, tmp_path):
        # The agent can replace the whole screenshots directory with a link
        # into runner space (its own /proc/self included): resolving such a
        # link as the trusted root would make every file under it pass the
        # containment check and be served.
        from app.main import get_screenshot
        from fastapi import HTTPException

        self._patch_root(monkeypatch, tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "environ").write_text("GITHUB_TOKEN=must-not-leave")
        directory = tmp_path / "7"
        directory.mkdir(parents=True)
        (directory / "screenshots").symlink_to(outside)

        with pytest.raises(HTTPException) as exc:
            await get_screenshot(session_id=7, name="environ", _=None)

        assert exc.value.status_code == 404
        # The target was never opened and stays untouched.
        assert (outside / "environ").exists()

    async def test_a_symlinked_file_is_not_served(self, monkeypatch, tmp_path):
        # The same trick one level down: a link named like a screenshot,
        # into a file outside the session's artefact directory.
        from app.main import get_screenshot
        from fastapi import HTTPException

        self._patch_root(monkeypatch, tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(b"runner file")
        directory = tmp_path / "7" / "screenshots"
        directory.mkdir(parents=True)
        (directory / "shot.png").symlink_to(outside / "secret.png")

        with pytest.raises(HTTPException) as exc:
            await get_screenshot(session_id=7, name="shot.png", _=None)

        assert exc.value.status_code == 404

    async def test_a_dangling_symlink_file_is_not_served(self, monkeypatch, tmp_path):
        from app.main import get_screenshot
        from fastapi import HTTPException

        self._patch_root(monkeypatch, tmp_path)
        directory = tmp_path / "7" / "screenshots"
        directory.mkdir(parents=True)
        (directory / "shot.png").symlink_to(tmp_path / "never-created")

        with pytest.raises(HTTPException) as exc:
            await get_screenshot(session_id=7, name="shot.png", _=None)

        assert exc.value.status_code == 404

    async def test_a_traversal_name_is_refused(self, monkeypatch, tmp_path):
        from app.main import get_screenshot
        from fastapi import HTTPException

        self._patch_root(monkeypatch, tmp_path)

        with pytest.raises(HTTPException) as exc:
            await get_screenshot(session_id=7, name="../secret.png", _=None)

        assert exc.value.status_code == 400

    async def test_a_missing_file_is_not_found(self, monkeypatch, tmp_path):
        from app.main import get_screenshot
        from fastapi import HTTPException

        self._patch_root(monkeypatch, tmp_path)
        (tmp_path / "7" / "screenshots").mkdir(parents=True)

        with pytest.raises(HTTPException) as exc:
            await get_screenshot(session_id=7, name="nope.png", _=None)

        assert exc.value.status_code == 404


class TestTheEndpointsThatCombineModules:
    """Routes that assemble their answer from several modules.

    Checking that the app *builds* does not exercise a single handler, so a
    function called with an argument it no longer takes passes every other
    test in this suite and raises on the first authenticated request. These
    call the handlers with their dependencies stubbed — not to pin the
    numbers, which the modules' own tests do, but to make signature drift
    between them fail here instead of in production.
    """

    async def test_capacity_answers(self, monkeypatch):
        from app import capacity, db, model_policy

        async def counts():
            return {"running": 1, "queued": 2, "paused": 0}

        async def policy():
            return model_policy.ModelPolicy(
                local_models=frozenset({"local-model"}),
                offered=("local-model",),
                local_deployments=frozenset({("15", "97")}),
                deployments_by_model={"local-model": frozenset({("15", "97")})},
                ok=True,
                unknown=False,
                detail="one local model",
            )

        async def reading(timeout_s: float = 5.0, lane=None):
            assert lane == frozenset({("15", "97")}), "the reading must be taken on the runner's own lane"
            return capacity.Reading(load=0.1, busy_slots=2, total_slots=20, queue_total=0, ok=True)

        monkeypatch.setattr(db, "count_sessions_by_status", counts)
        monkeypatch.setattr(model_policy, "refresh", policy)
        monkeypatch.setattr(model_policy, "_current", await policy())
        monkeypatch.setattr(capacity, "read_load", reading)

        state = await main.get_capacity()

        assert state.sessions_running == 1 and state.sessions_queued == 2
        assert state.may_start is True

    async def test_triggers_answers_with_the_quota_in_force(self, monkeypatch):
        from app import controls, db

        async def stored():
            return {"mode": "running", "mode_reason": "", "max_parallel": 2, "updated_by": "tobias"}

        async def active():
            return 1

        monkeypatch.setattr(controls.db, "get_controls", stored)
        monkeypatch.setattr(db, "count_active_trigger_sessions", active)
        controls.forget()

        status = await main.get_triggers()

        assert status["active_sessions"] == 1
        assert status["max_active_sessions"] <= 2


class TestRunningWorkAgain:
    """A failed session's request would otherwise be gone.

    The trigger counts as handled the moment a session exists for it, so no
    later pass finds that issue, review or question again — and the runner
    is the thing that failed, not the request.
    """

    ROW = {
        "id": 20,
        "workspace_id": 3,
        "workspace_name": "pr-858",
        "task": "answer the review on #858",
        "status": "failed",
        "model": None,
        "pr_url": None,
        "created_by": "LogosOSSAgent",
        "created_at": datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc),
        "started_at": None,
        "finished_at": None,
        "exit_code": 1,
        "error": "agent exited with code 1",
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "screenshot_count": 0,
        "open_pull_request": False,
        "trigger_kind": "review",
        "trigger_ref": "pr-858-review-5088907839",
        "branch_name": "logos/issue-797-dynamic-ram",
        "reply_target": "issue:858",
        "reaction_target": "/repos/x/y/issues/858",
        "priority": 80,
        "priority_reason": "a review is waiting",
    }

    def install(self, monkeypatch, *, status_value="failed"):
        from app import db, main, sessions

        created: list[dict] = []
        rows = {20: {**self.ROW, "status": status_value}}

        async def get_session(session_id):
            return rows.get(session_id)

        async def create_session(**kwargs):
            created.append(kwargs)
            rows[21] = {**self.ROW, "id": 21, "status": "queued"}
            return 21

        async def add_event(*_args, **_kwargs):
            return None

        async def scheduler_pass():
            return None

        monkeypatch.setattr(db, "get_session", get_session)
        monkeypatch.setattr(db, "create_session", create_session)
        monkeypatch.setattr(db, "add_event", add_event)
        monkeypatch.setattr(sessions.manager, "scheduler_pass", scheduler_pass)
        monkeypatch.setattr(main, "_summary_fields", lambda row: dict(row))
        return created

    async def test_the_work_is_queued_again_where_it_came_from(self, monkeypatch):
        created = self.install(monkeypatch)

        await main.retry_session(20, principal=_principal())

        assert created and created[0]["task"] == self.ROW["task"]
        assert created[0]["workspace_id"] == 3
        # The branch, the thread and the urgency belong to the request, not
        # to the attempt that failed.
        assert created[0]["branch"] == "logos/issue-797-dynamic-ram"
        assert created[0]["reply_target"] == "issue:858"
        assert created[0]["trigger_ref"] == "pr-858-review-5088907839"
        assert created[0]["priority"] == 80

    async def test_deploying_is_decided_per_attempt(self, monkeypatch):
        created = self.install(monkeypatch)

        await main.retry_session(20, principal=_principal())

        assert created[0]["deploy_to_dev"] is False

    async def test_a_session_still_running_is_refused(self, monkeypatch):
        from fastapi import HTTPException

        self.install(monkeypatch, status_value="running")

        with pytest.raises(HTTPException) as refused:
            await main.retry_session(20, principal=_principal())

        assert refused.value.status_code == 409

    async def test_an_unknown_session_is_not_found(self, monkeypatch):
        from fastapi import HTTPException

        self.install(monkeypatch)

        with pytest.raises(HTTPException) as missing:
            await main.retry_session(4711, principal=_principal())

        assert missing.value.status_code == 404


def _principal():
    from app.auth import Principal

    return Principal(subject="s", username="tobias", roles=frozenset({"agent-operator"}))
