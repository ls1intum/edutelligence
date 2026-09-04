"""Tests for the session state machine and the naming rules around it.

The branch derivation is security-relevant — it is what stops a session
pushing to a protected branch — so it is tested against hostile workspace
names, not just ordinary ones.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import replace

import pytest
from app.config import settings
from app.schemas import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    EventKind,
    SessionCreate,
    SessionStatus,
    WorkspaceCreate,
    can_transition,
)
from app.sessions import branch_for, container_name


class TestStateMachine:
    def test_normal_path(self):
        assert can_transition(SessionStatus.QUEUED, SessionStatus.STARTING)
        assert can_transition(SessionStatus.STARTING, SessionStatus.RUNNING)
        assert can_transition(SessionStatus.RUNNING, SessionStatus.SUCCEEDED)

    def test_pause_and_resume(self):
        assert can_transition(SessionStatus.RUNNING, SessionStatus.PAUSED)
        assert can_transition(SessionStatus.PAUSED, SessionStatus.RUNNING)

    def test_paused_never_returns_to_starting(self):
        # Re-running setup would wipe the working copy the pause preserved.
        assert not can_transition(SessionStatus.PAUSED, SessionStatus.STARTING)

    def test_terminal_states_are_final(self):
        for status in TERMINAL_STATUSES:
            for target in SessionStatus:
                assert not can_transition(status, target), f"{status} -> {target}"

    def test_every_active_state_can_be_cancelled(self):
        for status in ACTIVE_STATUSES:
            assert can_transition(status, SessionStatus.CANCELLED)

    def test_queued_cannot_jump_straight_to_running(self):
        # Running means a container exists; skipping starting would leave the
        # row claiming a container that was never created.
        assert not can_transition(SessionStatus.QUEUED, SessionStatus.RUNNING)

    def test_finalizing_is_claimed_from_running(self):
        # Settlement claims the non-pausable state before the finalizer
        # helper starts, so the scheduler can no longer see the row as
        # running once the agent container is gone.
        assert can_transition(SessionStatus.RUNNING, SessionStatus.FINALIZING)

    def test_finalizing_never_returns_to_running_or_paused(self):
        # Pausing would have nothing left to freeze (the agent container is
        # gone), and a resume would hand the row back with no supervisor to
        # finish it — the stranded-session race this state exists to close.
        assert not can_transition(SessionStatus.FINALIZING, SessionStatus.PAUSED)
        assert not can_transition(SessionStatus.FINALIZING, SessionStatus.RUNNING)

    def test_finalizing_reaches_its_outcomes(self):
        for target in (SessionStatus.SUCCEEDED, SessionStatus.FAILED, SessionStatus.CANCELLED):
            assert can_transition(SessionStatus.FINALIZING, target)


class TestBranchDerivation:
    def test_branch_carries_the_configured_prefix(self):
        branch = branch_for(7, "feature-work")
        assert branch.startswith(settings.branch_prefix)
        assert branch.endswith("session-7")

    def test_two_sessions_never_share_a_branch(self):
        assert branch_for(1, "same") != branch_for(2, "same")

    @pytest.mark.parametrize(
        "hostile",
        ["../../main", "main", "..", "a/../../../etc", "with space", "sem;icolon"],
    )
    def test_hostile_workspace_names_cannot_escape_the_prefix(self, hostile):
        branch = branch_for(3, hostile)
        assert branch.startswith(settings.branch_prefix)
        assert ".." not in branch
        # Whatever the name was, the branch still ends in this session's own
        # segment, so it cannot resolve to a protected branch.
        assert branch.endswith("session-3")
        assert branch.rsplit("/", 1)[-1] not in settings.protected_branches

    def test_empty_name_still_produces_a_usable_branch(self):
        branch = branch_for(4, "")
        assert branch.startswith(settings.branch_prefix)
        assert "//" not in branch.removeprefix(settings.branch_prefix)


class TestContainerNaming:
    def test_name_is_derived_from_the_session_id(self):
        assert container_name(12) != container_name(13)
        assert "12" in container_name(12)


class TestRequestValidation:
    def test_workspace_name_is_reduced_to_safe_characters(self):
        assert WorkspaceCreate(name="My Feature!").name == "my-feature-"

    def test_workspace_name_must_contain_something_usable(self):
        with pytest.raises(ValueError):
            WorkspaceCreate(name="   ---   ")

    def test_task_must_not_be_trivial(self):
        with pytest.raises(ValueError):
            SessionCreate(workspace_id=1, task="fix")

    def test_screenshot_paths_must_be_absolute_paths(self):
        with pytest.raises(ValueError):
            SessionCreate(
                workspace_id=1,
                task="a long enough task description",
                screenshot_paths=["https://example.com/evil"],
            )

    def test_protocol_relative_paths_are_refused(self):
        # "//evil.example" would resolve to another host once joined to the
        # dev base URL, taking the screenshot off-platform.
        with pytest.raises(ValueError):
            SessionCreate(
                workspace_id=1,
                task="a long enough task description",
                screenshot_paths=["//evil.example/page"],
            )

    def test_ordinary_paths_pass(self):
        body = SessionCreate(
            workspace_id=1,
            task="a long enough task description",
            screenshot_paths=["/dashboard", "/models"],
        )
        assert body.screenshot_paths == ["/dashboard", "/models"]


class TestLaunchAndSupervision:
    """What the manager decides to do with a container.

    These run against fakes of the Docker engine and the database, so they pin
    down the decisions — what gets bound into a session, what gets removed
    when a start fails, and how the wall-clock budget treats paused time —
    without needing a daemon.
    """

    SESSION = {
        "id": 7,
        "workspace_id": 1,
        "task": "a long enough task description",
        "model": None,
        "open_pull_request": False,
        "screenshot_paths": [],
    }
    WORKSPACE = {
        "id": 1,
        "name": "feature-work",
        "base_branch": "main",
        "volume_name": "logos-agent-ws-1",
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_failed_launch_removes_its_container_and_binds_its_own_artifacts(self, monkeypatch, tmp_path):
        # A start that fails after the container exists must not leak it:
        # settlement removes the container by the id in the database, which is
        # still null at that point. And the artefact bind must be this
        # session's own directory on the host, not the shared volume.
        from app import sessions

        patched = replace(sessions.settings, artifact_root=str(tmp_path))
        monkeypatch.setattr(sessions, "settings", patched)
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        created: list = []
        removed: list = []
        starts: list = []
        container_ids = iter(["cid-prepare", "cid-7"])

        async def fake_create(**kwargs):
            created.append(kwargs)
            return next(container_ids)

        async def fake_start(cid):
            starts.append(cid)
            if len(starts) == 2:
                # The prepare helper ran; the agent container's start fails.
                raise RuntimeError("start failed")

        async def fake_wait(_cid, **_kwargs):
            return 0

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(
            sessions.docker_engine,
            "volume_mountpoint",
            self._async_value("/var/lib/docker/volumes/logos_agent_artifacts/_data"),
        )
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(
            sessions.db, "get_session", self._async_value({"container_id": None, "deploy_to_dev": False})
        )
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._launch(self.SESSION)

        # Neither container leaks: the helper removes its own, the launch
        # removes the agent container it just failed to start.
        assert removed == ["cid-prepare", "cid-7"]
        # Two containers: the trusted prepare helper first, the agent second.
        assert [c["env"]["LOGOS_SESSION_PHASE"] for c in created] == ["prepare", "agent"]
        agent = created[-1]
        assert agent["artifact_host_path"] == "/var/lib/docker/volumes/logos_agent_artifacts/_data/7"
        # Model traffic is pointed at the gateway, not at the orchestrator's
        # internal API: the session network must not reach the orchestrator.
        assert agent["env"]["ANTHROPIC_BASE_URL"] == patched.session_model_url
        assert agent["env"]["ANTHROPIC_BASE_URL"] != patched.orchestrator_url
        # The bind source *is* the session's output directory, so the session
        # writes into /artifacts itself — a per-session prefix here would put
        # its output one directory too deep.
        assert agent["env"]["LOGOS_ARTIFACT_DIR"] == "/artifacts"

    async def test_paused_time_does_not_count_towards_the_session_timeout(self, monkeypatch, tmp_path):
        # A session that yields while the platform is busy must not burn its
        # wall-clock budget standing by: the deadline is frozen for as long as
        # the container is paused, and enforced again once it runs.
        from app import sessions

        monkeypatch.setattr(
            sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path), session_timeout_s=1)
        )
        states = {"state": "paused"}
        stopped: list = []
        events: list = []

        async def fake_state(_cid):
            return states["state"], None

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)

        async def fake_remove(_cid, **_kwargs):
            return None

        async def fake_stream(_cid, **_kwargs):
            while True:
                await asyncio.sleep(3600)
                yield ""

        async def fake_event(_sid, _kind, payload):
            events.append(payload)

        monkeypatch.setattr(sessions.docker_engine, "container_state", fake_state)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", fake_stream)
        monkeypatch.setattr(
            sessions.db, "get_session", self._async_value({"container_id": "cid-9", "deploy_to_dev": False})
        )
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        supervisor = asyncio.create_task(sessions.manager._supervise_session(9, "cid-9"))
        try:
            # Paused well past the one-second budget: standing by must not spend it.
            await asyncio.sleep(2.5)
            assert stopped == []
            assert not supervisor.done()

            # Back to work: the remaining budget now runs down and is enforced.
            states["state"] = "running"
            for _ in range(20):
                if stopped:
                    break
                await asyncio.sleep(0.25)
            assert stopped == ["cid-9"]
            await supervisor
        finally:
            if not supervisor.done():
                supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await supervisor

        assert any("exceeded" in str(payload.get("message", "")) for payload in events)

    async def test_a_cancel_racing_the_launch_stops_and_removes_the_container(self, monkeypatch, tmp_path):
        # If an operator cancels while the container is being created or
        # started, the row leaves 'starting' before the launch can claim
        # 'running'. The launch must give up the container it just started —
        # no running event, no supervision, no settlement, none of the
        # completion side effects that a live, credentialed container would
        # otherwise still be allowed to perform.
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        stopped: list = []
        removed: list = []
        events: list = []
        transitions: list = []

        async def fake_transition(sid, target, **fields):
            transitions.append(target)
            return False

        async def fake_stop(cid, **kwargs):
            stopped.append(cid)

        async def fake_remove(cid, **kwargs):
            removed.append(cid)

        async def fake_event(sid, kind, payload):
            events.append((kind, payload))

        async def fake_create(**kwargs):
            return next(container_ids)

        async def fake_wait(_cid, **_kwargs):
            return 0

        async def noop(*args, **kwargs):
            return None

        container_ids = iter(["cid-prepare", "cid-7"])
        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._launch(self.SESSION)

        # The prepare helper already ran to completion and cleaned up after
        # itself; only the agent container is stopped by the lost transition.
        assert stopped == ["cid-7"]
        assert removed == ["cid-prepare", "cid-7"]
        # One transition attempt (to running), and no settlement afterwards:
        # the row belongs to the cancel, not to this launch.
        assert transitions == [SessionStatus.RUNNING]
        assert events == []
        assert not sessions.manager._supervisors

    async def test_a_settle_racing_the_cancel_loses_to_it(self, monkeypatch, tmp_path):
        # While the cancel's stop is in flight the supervisor can observe
        # the exit and settle it. The cancel must own the row before any
        # container I/O, so the settle's terminal transition loses and the
        # session ends CANCELLED — no succeeded event, no deploy, no
        # screenshots for a session the operator just cancelled.
        from app import sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), deploy_enabled=True),
        )
        row = {
            "status": "running",
            "container_id": "cid-7",
            "deploy_to_dev": True,
            "branch_name": "agent/feature-work/session-7",
            "screenshot_paths": ["/dashboard"],
        }
        order: list = []
        removed: list = []
        dispatched: list = []
        events: list = []
        claimed: dict = {}

        async def fake_transition(sid, target, **_fields):
            order.append(("transition", target))
            # The atomic gate: the row moves once, to whatever claims it
            # first; every later transition loses.
            if sid in claimed:
                return False
            claimed[sid] = target
            return True

        async def fake_stop(_cid, **_kwargs):
            order.append("stop")
            # The supervisor settles the exit it observes while the stop is
            # in flight.
            await sessions.manager._settle(7, exit_code=0, error=None)

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        # The settled exit is a clean one, so settlement would run the
        # finalizer; this test is about the cancel race, not the helper.
        monkeypatch.setattr(sessions.SessionManager, "_finalize", self._async_value(True))

        moved = await sessions.manager.cancel(7)

        assert moved is True
        # The claim comes first: CANCELLED before the stop, and the
        # settle's finalizing claim — the move that would have handed the
        # session to the finalizer — loses the race to it.
        assert order == [("transition", SessionStatus.CANCELLED), "stop", ("transition", SessionStatus.FINALIZING)]
        assert dispatched == []
        assert events == [(EventKind.STATUS, {"status": "cancelled"})]
        assert removed.count("cid-7") >= 1


class TestPermissionsRevokedMidFlight:
    """A key can lose its local model while sessions are running.

    Permissions are data: the key can be granted a cloud provider, or have
    its local one taken away, long after a session started. What must not
    happen is a session carrying on — or being resumed — on a permission
    that no longer exists.
    """

    @staticmethod
    def install(monkeypatch, *, running=(), paused=()):
        from app import capacity, model_policy, sessions

        revoked = model_policy.ModelPolicy(
            ok=False,
            unknown=False,
            detail="the agent key reaches no locally served model",
        )
        paused_sessions: list = []
        resumed: list = []

        async def refresh():
            return revoked

        async def read_load(timeout_s: float = 5.0, lane=None, ours=None):
            # The lane an invalid policy hands over is empty, and an empty
            # lane is refused rather than measured.
            assert lane == frozenset()
            return capacity.parse_scheduler_state({"queue_total": 0}, lane=lane)

        async def sessions_in_status(status):
            if status is sessions.SessionStatus.RUNNING:
                return list(running)
            if status is sessions.SessionStatus.PAUSED:
                return list(paused)
            return []

        async def fake_pause(_self, session, reason):
            paused_sessions.append((session["id"], reason))

        async def fake_resume(_self, session, reason):
            resumed.append(session["id"])

        monkeypatch.setattr(model_policy, "refresh", refresh)
        monkeypatch.setattr(model_policy, "_current", revoked)
        monkeypatch.setattr(capacity, "read_load", read_load)
        monkeypatch.setattr(sessions.db, "sessions_in_status", sessions_in_status)
        monkeypatch.setattr(sessions.SessionManager, "_pause", fake_pause)
        monkeypatch.setattr(sessions.SessionManager, "_resume", fake_resume)
        return paused_sessions, resumed

    async def test_a_running_session_is_handed_back(self, monkeypatch):
        from app import sessions

        paused_sessions, _ = self.install(monkeypatch, running=[{"id": 7, "container_id": "cid-7"}])

        await sessions.manager.scheduler_pass()

        assert [sid for sid, _ in paused_sessions] == [7]

    async def test_a_paused_session_is_not_resumed(self, monkeypatch):
        from app import sessions

        _, resumed = self.install(monkeypatch, paused=[{"id": 7, "container_id": "cid-7"}])

        await sessions.manager.scheduler_pass()

        assert resumed == []


class TestOnePieceOfWork:
    """A pull request is worked on by one workspace, across its rounds.

    An issue becomes a change, a review comes back, then another. Each round
    in the same working copy, continuing the same conversation, instead of
    re-reading the repository from scratch for a change of ten lines.
    """

    async def test_the_same_branch_continues(self, monkeypatch):
        from app import sessions

        async def previous(_workspace_id, *, before_session_id):
            return "logos/agent/pr-858/session-3"

        monkeypatch.setattr(sessions.db, "last_session_branch", previous)

        assert await sessions.manager._continues_earlier_work(
            {"id": 9, "workspace_id": 1}, "logos/agent/pr-858/session-3"
        )

    async def test_a_workspace_pointed_elsewhere_starts_clean(self, monkeypatch):
        from app import sessions

        async def previous(_workspace_id, *, before_session_id):
            return "logos/agent/pr-772/session-1"

        monkeypatch.setattr(sessions.db, "last_session_branch", previous)

        assert not await sessions.manager._continues_earlier_work({"id": 9, "workspace_id": 1}, "logos/other")

    async def test_the_first_session_in_a_workspace_starts_clean(self, monkeypatch):
        from app import sessions

        async def previous(_workspace_id, *, before_session_id):
            return None

        monkeypatch.setattr(sessions.db, "last_session_branch", previous)

        assert not await sessions.manager._continues_earlier_work({"id": 9, "workspace_id": 1}, "logos/agent/x")

    async def test_a_workspace_with_an_open_pull_request_is_kept(self, monkeypatch):
        from app import sessions

        async def open_pr(branch):
            return {"number": 858} if branch == "logos/agent/pr-858/session-3" else None

        monkeypatch.setattr(sessions.github, "open_pull_request_for", open_pr)

        # Idle for hours, and still not finished: the next review continues
        # it, and the volume holds the conversation that would be lost.
        assert await sessions.manager._still_wanted({"name": "pr-858", "base_branch": "logos/agent/pr-858/session-3"})
        assert not await sessions.manager._still_wanted({"name": "auto-1", "base_branch": "logos/agent/pr-772/old"})

    async def test_a_workspace_is_kept_when_github_cannot_be_asked(self, monkeypatch):
        from app import sessions

        async def broken(_branch):
            raise RuntimeError("502")

        monkeypatch.setattr(sessions.github, "open_pull_request_for", broken)

        # Losing a working copy because GitHub was briefly unreachable is
        # the more expensive mistake.
        assert await sessions.manager._still_wanted({"name": "pr-858", "base_branch": "logos/agent/pr-858/x"})

    async def test_a_workspace_on_a_protected_branch_is_not_kept(self, monkeypatch):
        from app import sessions

        async def refuse(_branch):
            raise AssertionError("main is not a pull request branch")

        monkeypatch.setattr(sessions.github, "open_pull_request_for", refuse)

        assert not await sessions.manager._still_wanted({"name": "auto-1", "base_branch": "main"})


class TestTranscript:
    """What the person watching a session sees, and when.

    A session that prints a handful of lines a minute — which is what
    reading code and running tests looks like — used to fill a batch of
    twenty only after several minutes, so working sessions looked hung.
    """

    async def test_output_appears_without_waiting_for_a_full_batch(self, monkeypatch):
        from app import sessions

        monkeypatch.setattr(sessions, "LOG_FLUSH_S", 0.05)
        events: list = []

        async def add_event(session_id, kind, payload):
            events.append((kind, payload))

        async def three_lines(_cid, **_kwargs):
            for line in ("[session] starting agent", "[tool] Bash", "reading the failing test"):
                yield line
            # Then the agent thinks for a while, as agents do.
            await asyncio.sleep(0.4)

        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", three_lines)

        collector = asyncio.create_task(sessions.manager._collect_logs(7, "cid-7"))
        await asyncio.sleep(0.2)
        collector.cancel()

        assert events, "three lines must not wait for a batch of twenty"
        assert events[0][1]["lines"] == [
            "[session] starting agent",
            "[tool] Bash",
            "reading the failing test",
        ]

    async def test_usage_the_agent_reports_reaches_the_row(self, monkeypatch):
        from app import sessions

        monkeypatch.setattr(sessions, "LOG_FLUSH_S", 0.05)
        recorded: list = []

        async def add_event(*_args, **_kwargs):
            return None

        async def update_session_usage(session_id, *, tokens_in, tokens_out):
            recorded.append((session_id, tokens_in, tokens_out))

        async def lines(_cid, **_kwargs):
            yield "[usage] in=100 out=10"
            yield "[tool] Bash"
            yield "[usage] in=4200 out=310"
            await asyncio.sleep(0.4)

        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.db, "update_session_usage", update_session_usage)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", lines)

        collector = asyncio.create_task(sessions.manager._collect_logs(7, "cid-7"))
        await asyncio.sleep(0.2)
        collector.cancel()

        # The newest line in the batch, not the first: the numbers are a
        # running total and only the latest one is current.
        assert recorded == [(7, 4200, 310)]

    async def test_a_line_without_an_output_figure_still_records_the_input(self, monkeypatch):
        from app import sessions

        monkeypatch.setattr(sessions, "LOG_FLUSH_S", 0.05)
        recorded: list = []

        async def add_event(*_args, **_kwargs):
            return None

        async def update_session_usage(session_id, *, tokens_in, tokens_out):
            recorded.append((session_id, tokens_in, tokens_out))

        async def lines(_cid, **_kwargs):
            # What a run in flight looks like: the output count only exists
            # once the invocation reports its total, and the column only
            # ever moves upwards, so zero leaves the last known one standing.
            yield "[usage] in=4200"
            await asyncio.sleep(0.4)

        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.db, "update_session_usage", update_session_usage)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", lines)

        collector = asyncio.create_task(sessions.manager._collect_logs(7, "cid-7"))
        await asyncio.sleep(0.2)
        collector.cancel()

        assert recorded == [(7, 4200, 0)]

    async def test_ordinary_output_records_no_usage(self, monkeypatch):
        from app import sessions

        monkeypatch.setattr(sessions, "LOG_FLUSH_S", 0.05)

        async def add_event(*_args, **_kwargs):
            return None

        async def refuse(*_args, **_kwargs):
            raise AssertionError("no usage line, nothing to record")

        async def lines(_cid, **_kwargs):
            yield "[tool] Bash"
            await asyncio.sleep(0.4)

        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.db, "update_session_usage", refuse)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", lines)

        collector = asyncio.create_task(sessions.manager._collect_logs(7, "cid-7"))
        await asyncio.sleep(0.2)
        collector.cancel()


class TestStandingDown:
    """What a deploy does to work that is under way.

    The runner and the model gateway are replaced together. A session left
    running keeps talking to a gateway being restarted underneath it and
    loses the turn it was in the middle of; frozen first, it loses nothing.
    """

    async def test_running_sessions_are_frozen_before_the_process_goes(self, monkeypatch):
        from app import sessions

        paused: list = []

        async def running(status):
            return [{"id": 7, "container_id": "cid-7"}] if status is sessions.SessionStatus.RUNNING else []

        async def fake_pause(_self, session, reason):
            paused.append((session["id"], reason))

        monkeypatch.setattr(sessions.db, "sessions_in_status", running)
        monkeypatch.setattr(sessions.SessionManager, "_pause", fake_pause)

        await sessions.manager._stand_down()

        assert paused == [(7, "the runner is restarting")]

    async def test_a_pause_that_hangs_does_not_hold_the_shutdown(self, monkeypatch):
        from app import sessions

        monkeypatch.setattr(sessions, "STAND_DOWN_S", 0.05)

        async def running(status):
            return [{"id": 7, "container_id": "cid-7"}] if status is sessions.SessionStatus.RUNNING else []

        async def hangs(_self, _session, _reason):
            await asyncio.sleep(30)

        monkeypatch.setattr(sessions.db, "sessions_in_status", running)
        monkeypatch.setattr(sessions.SessionManager, "_pause", hangs)

        # Docker is going to kill this process shortly either way; a session
        # that cannot be frozen in time is left running, as before.
        await asyncio.wait_for(sessions.manager._stand_down(), timeout=2.0)

    async def test_a_container_whose_row_is_still_starting_is_frozen_too(self, monkeypatch):
        # Between the container start and the move to running, the row has
        # no container id and may not become paused — but the agent is live
        # and talking to a gateway that is about to be replaced.
        from app import sessions

        paused: list = []

        async def rows(status):
            return [{"id": 9}] if status is sessions.SessionStatus.STARTING else []

        async def containers():
            return [
                {"Id": "cid-9", "State": "running", "Labels": {"logos.agent.session": "9"}},
                {"Id": "cid-helper", "State": "running", "Labels": {"logos.agent.helper": "prepare"}},
                {"Id": "cid-8", "State": "exited", "Labels": {"logos.agent.session": "8"}},
            ]

        async def fake_pause(cid, **_kwargs):
            paused.append(cid)
            return True

        monkeypatch.setattr(sessions.db, "sessions_in_status", rows)
        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", containers)
        monkeypatch.setattr(sessions.docker_engine, "pause_container", fake_pause)

        await sessions.manager._stand_down()

        # Only the live session container: not the helper, not a container
        # that has already exited.
        assert paused == ["cid-9"]

    async def test_a_launch_with_no_supervisor_yet_is_still_frozen(self, monkeypatch):
        # The gap this exists for: a launch cancelled between starting its
        # container and registering a supervisor leaves nothing in memory
        # and a live agent on the host. Bookkeeping that says "nothing is
        # running" must not be what decides.
        from app import sessions

        paused: list = []

        async def rows(status):
            return [{"id": 9}] if status is sessions.SessionStatus.STARTING else []

        async def containers():
            return [{"Id": "cid-9", "State": "running", "Labels": {"logos.agent.session": "9"}}]

        async def fake_pause(cid, **_kwargs):
            paused.append(cid)
            return True

        monkeypatch.setattr(sessions.db, "sessions_in_status", rows)
        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", containers)
        monkeypatch.setattr(sessions.docker_engine, "pause_container", fake_pause)

        assert not sessions.manager._supervisors
        await sessions.manager._stand_down()

        assert paused == ["cid-9"]

    async def test_an_unreadable_database_does_not_break_shutdown(self, monkeypatch):
        from app import sessions

        async def broken(_status):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(sessions.db, "sessions_in_status", broken)

        await sessions.manager._stand_down()


class TestBackpressure:
    """Output must not be able to grow into a memory problem."""

    async def test_a_session_that_outruns_the_database_still_arrives(self, monkeypatch):
        from app import sessions

        monkeypatch.setattr(sessions, "LOG_FLUSH_S", 0.01)
        monkeypatch.setattr(sessions, "LOG_QUEUE_MAX", 3)
        monkeypatch.setattr(sessions, "LOG_BATCH_LINES", 2)
        written: list[str] = []

        async def slow_add_event(_session_id, _kind, payload):
            # The database is the slow end here, which is the case the
            # bound exists for.
            await asyncio.sleep(0.01)
            written.extend(payload["lines"])

        async def chatty(_cid, **_kwargs):
            for index in range(20):
                yield f"line {index}"

        monkeypatch.setattr(sessions.db, "add_event", slow_add_event)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", chatty)

        # Returns when the stream ends: a reader blocked on a full queue
        # nobody drains would hang here instead.
        await asyncio.wait_for(sessions.manager._collect_logs(7, "cid-7"), timeout=5.0)

        assert written == [f"line {index}" for index in range(20)]

    async def test_the_end_of_the_stream_is_not_lost_to_a_full_queue(self, monkeypatch):
        # With no room for the end-of-stream marker, the writer has to go by
        # the reader being finished instead — waiting for a marker that was
        # dropped would wait forever.
        from app import sessions

        monkeypatch.setattr(sessions, "LOG_FLUSH_S", 0.01)
        monkeypatch.setattr(sessions, "LOG_QUEUE_MAX", 1)
        monkeypatch.setattr(sessions, "LOG_BATCH_LINES", 50)
        written: list[str] = []

        async def add_event(_session_id, _kind, payload):
            written.extend(payload["lines"])

        async def one_line(_cid, **_kwargs):
            yield "the only line"

        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.docker_engine, "stream_logs", one_line)

        await asyncio.wait_for(sessions.manager._collect_logs(7, "cid-7"), timeout=5.0)

        assert written == ["the only line"]


class TestAnAnswerThatWasNeverWritten:
    """A session that wrote nothing has nothing to say.

    Somebody is waiting to hear about their pull request, not about the
    runner. So a session that finishes without a word is not announced —
    the request is taken up again, and the thread hears from the attempt
    that has something to report.
    """

    @staticmethod
    def install(monkeypatch, tmp_path, row):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        posted: list = []
        attempts: list = []

        async def get_session(_session_id):
            return row

        async def post_issue_comment(number, body):
            posted.append((number, body))
            return f"https://github.com/x/y/issues/{number}#issuecomment-1"

        async def record_reply_attempt(session_id, *, delivered):
            attempts.append((session_id, delivered))

        async def abandon_reply(_session_id, *, attempts):
            return None

        async def add_event(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", get_session)
        monkeypatch.setattr(sessions.db, "record_reply_attempt", record_reply_attempt)
        monkeypatch.setattr(sessions.db, "abandon_reply", abandon_reply)
        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.github, "post_issue_comment", post_issue_comment)
        return posted, attempts

    async def test_a_silent_session_is_taken_up_again_rather_than_announced(self, monkeypatch, tmp_path):
        from app import sessions

        posted, _ = self.install(
            monkeypatch,
            tmp_path,
            # Succeeded and said nothing: the case this path owns. A failed
            # one is taken up by its settlement, which is where the reason
            # for the failure is.
            {"id": 30, "status": "succeeded", "reply_target": "issue:886", "reply_posted_at": None, "pr_url": None},
        )
        taken_up: list = []

        async def take_up_again(_self, session, *, by="the runner"):
            taken_up.append(session["id"])
            return 99

        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)

        await sessions.manager._post_reply(30)

        # "The session failed, run it again from the page" is the runner
        # talking about itself in front of people who asked about their
        # pull request. What it means is that the request was not dealt
        # with — so it is dealt with again.
        assert posted == []
        assert taken_up == [30]

    async def test_what_the_agent_wrote_is_posted(self, monkeypatch, tmp_path):
        from app import sessions

        posted, _ = self.install(
            monkeypatch,
            tmp_path,
            {"id": 30, "status": "succeeded", "reply_target": "issue:886", "reply_posted_at": None},
        )
        directory = tmp_path / "30"
        directory.mkdir()
        (directory / "reply.md").write_text("The alignment is fixed by the flex rule on line 42.")

        await sessions.manager._post_reply(30)

        assert posted[0][1] == "The alignment is fixed by the flex rule on line 42."

    async def test_an_unreadable_file_is_retried_rather_than_abandoned(self, monkeypatch, tmp_path):
        # A mount that is not there yet is not an answer that was never
        # written: the file may well be readable on the next pass.
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        attempts: list = []

        async def get_session(_session_id):
            return {"id": 7, "reply_target": "issue:772", "reply_posted_at": None}

        async def record_reply_attempt(session_id, *, delivered):
            attempts.append((session_id, delivered))

        async def refuse(*_args, **_kwargs):
            raise AssertionError("an unreadable file must not be given up on")

        def unreadable(*_args, **_kwargs):
            raise PermissionError("permission denied")

        monkeypatch.setattr(sessions.db, "get_session", get_session)
        monkeypatch.setattr(sessions.db, "record_reply_attempt", record_reply_attempt)
        monkeypatch.setattr(sessions.db, "abandon_reply", refuse)
        monkeypatch.setattr(sessions.Path, "read_text", unreadable)

        await sessions.manager._post_reply(7)

        assert attempts == [(7, False)]


class TestReactionsOnAThread:
    """What a person watching their own comment gets to see.

    Three states, and GitHub's fixed palette to say them in: the queueing
    pass leaves an eye when the work is accepted, the launch adds a rocket
    when it actually starts, and a session that fails says so rather than
    leaving a thread that looks like it is still being worked on.
    """

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_a_starting_session_says_so_on_its_thread(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        reactions: list = []
        starts: list = []
        container_ids = iter(["cid-prepare", "cid-7"])

        async def fake_create(**_kwargs):
            return next(container_ids)

        async def fake_start(cid):
            starts.append(cid)

        async def fake_react(path, content="eyes"):
            reactions.append((path, content))
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(
            sessions.docker_engine,
            "volume_mountpoint",
            self._async_value("/var/lib/docker/volumes/logos_agent_artifacts/_data"),
        )
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", self._async_value(0))
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(TestLaunchAndSupervision.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", noop)
        monkeypatch.setattr(sessions.github, "react", fake_react)
        # On the class: an instance attribute would outlive the test and
        # shadow the patches other tests make on the class.
        monkeypatch.setattr(sessions.SessionManager, "_supervise", lambda *_args, **_kwargs: None)

        session = dict(TestLaunchAndSupervision.SESSION)
        session["reaction_target"] = "/repos/ls1intum/edutelligence/issues/comments/9001"

        await sessions.manager._launch(session)

        assert reactions == [(session["reaction_target"], sessions.github.REACTION_RUNNING)]

    async def test_a_session_nobody_asked_for_reacts_nowhere(self, monkeypatch):
        # Sessions started from the page have no thread behind them.
        from app import sessions

        async def refuse(*_args, **_kwargs):
            raise AssertionError("a session with no target must not react")

        monkeypatch.setattr(sessions.github, "react", refuse)

        await sessions.manager._react({"id": 7}, sessions.github.REACTION_RUNNING)

    async def test_a_reaction_github_refuses_does_not_fail_the_session(self, monkeypatch):
        from app import sessions

        async def broken(*_args, **_kwargs):
            raise RuntimeError("403")

        monkeypatch.setattr(sessions.github, "react", broken)

        # No exception: the work is what matters, the emoji is not.
        await sessions.manager._react({"reaction_target": "/x"}, sessions.github.REACTION_FAILED)


class TestAgentPhaseIsolation:
    """What the untrusted agent phase may hold and reach.

    The agent runs with permission prompts disabled, so a hostile task or a
    poisoned repository instruction can steer it anywhere its credentials
    and network allow. It therefore carries no reusable credential and no
    unrestricted egress: model traffic goes to the credential-injecting
    gateway on the internal network, and the GitHub operations run in the
    runner-owned helper phases instead.
    """

    SESSION = {
        "id": 7,
        "workspace_id": 1,
        "task": "a long enough task description",
        "model": None,
        "open_pull_request": True,
        "screenshot_paths": [],
    }
    WORKSPACE = {
        "id": 1,
        "name": "feature-work",
        "base_branch": "main",
        "volume_name": "logos-agent-ws-1",
    }
    ROW = {
        "id": 7,
        "workspace_id": 1,
        "status": "running",
        "container_id": "cid-7",
        "branch_name": "agent/feature-work/session-7",
        "task": "a long enough task description",
        "deploy_to_dev": False,
        "open_pull_request": True,
        "screenshot_paths": [],
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path):
        from app import sessions

        patched = replace(sessions.settings, artifact_root=str(tmp_path), session_github_token="ghp-session-token")
        monkeypatch.setattr(sessions, "settings", patched)
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))
        return patched

    async def test_the_agent_phase_carries_no_reusable_credentials(self, monkeypatch, tmp_path):
        # Launch runs two containers: the trusted prepare helper (egress,
        # push token) and the agent (internal network, nothing reusable).
        from app import sessions

        patched = self._patch_base(monkeypatch, tmp_path)
        created: list = []
        supervised: list = []
        container_ids = iter(["cid-prepare", "cid-7"])

        async def fake_create(**kwargs):
            created.append(kwargs)
            return next(container_ids)

        async def fake_wait(_cid, **_kwargs):
            return 0

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", noop)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)

        await sessions.manager._launch(self.SESSION)

        assert [c["env"]["LOGOS_SESSION_PHASE"] for c in created] == ["prepare", "agent"]
        prepare, agent = created

        # The helper gets the scoped token and the egress network.
        assert prepare["env"]["GITHUB_TOKEN"] == "ghp-session-token"
        assert prepare["network"] == patched.session_egress_network
        assert prepare["labels"] == {"logos.agent.helper": "prepare"}

        # The agent gets neither: no GitHub token in any form, and the model
        # credential is a placeholder the gateway replaces — the real key
        # never enters the container. It stays on the internal network,
        # where the gateway is the only peer.
        assert "GITHUB_TOKEN" not in agent["env"]
        assert "GH_TOKEN" not in agent["env"]
        assert agent["env"]["ANTHROPIC_AUTH_TOKEN"] == "injected-by-logos-agent-gateway"
        assert agent["env"]["ANTHROPIC_BASE_URL"] == patched.session_model_url
        assert agent.get("network") is None
        assert not agent.get("labels")
        # Only the agent container is a supervised session.
        assert supervised == [(7, "cid-7")]

    async def test_a_successful_settlement_runs_the_trusted_finalizer(self, monkeypatch, tmp_path):
        # The agent phase pushed nothing: with a clean agent exit, settlement
        # runs the finalize helper — the container that commits, pushes, and
        # opens the pull request with the scoped token. The row leaves
        # 'running' (into the non-pausable finalizing state) before the
        # helper exists, so a scheduler pass can never pause it underneath.
        from app import sessions

        patched = self._patch_base(monkeypatch, tmp_path)
        created: list = []
        removed: list = []
        order: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            order.append(("helper", "created"))
            return "cid-finalize"

        async def fake_wait(_cid, **_kwargs):
            return 0

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_transition(_sid, target, **_fields):
            order.append(("transition", target))
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.ROW))
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The finalizing claim precedes the helper; the terminal transition
        # comes after it.
        assert order[0] == ("transition", SessionStatus.FINALIZING)
        assert order.index(("helper", "created")) > 0
        assert [target for kind, target in order if kind == "transition"] == [
            SessionStatus.FINALIZING,
            SessionStatus.SUCCEEDED,
        ]

        assert len(created) == 1
        helper = created[0]
        assert helper["name"] == "logos-agent-finalize-7"
        assert helper["env"]["LOGOS_SESSION_PHASE"] == "finalize"
        assert helper["env"]["GITHUB_TOKEN"] == "ghp-session-token"
        assert helper["env"]["GH_TOKEN"] == "ghp-session-token"
        assert helper["env"]["LOGOS_REPO_URL"] == patched.repo_url
        assert helper["env"]["LOGOS_SESSION_OPEN_PR"] == "1"
        assert helper["network"] == patched.session_egress_network
        assert helper["labels"] == {"logos.agent.helper": "finalize"}
        # The helper is a one-shot: created, waited on, removed.
        assert removed == ["cid-finalize", "cid-7"]

    async def test_a_failed_agent_run_is_not_finalized(self, monkeypatch, tmp_path):
        # A crashed agent left nothing worth committing: no finalizer runs,
        # and no authenticated GitHub operation happens at all.
        from app import sessions

        self._patch_base(monkeypatch, tmp_path)
        created: list = []
        transitions: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-finalize"

        async def fake_transition(_sid, target, **_fields):
            transitions.append(target)
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.ROW))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._settle(7, exit_code=1, error=None)

        assert created == []
        assert transitions == [SessionStatus.FAILED]

    async def test_a_failed_finalizer_fails_the_session(self, monkeypatch, tmp_path):
        # The agent exited cleanly but the push did not happen (the helper
        # failed): settling that as a success would dispatch a deploy behind
        # work that never reached the repository. The session is failed
        # instead, with the reason recorded.
        from app import sessions

        self._patch_base(monkeypatch, tmp_path)
        transitions: list = []

        async def fake_create(**_kwargs):
            return "cid-finalize"

        async def fake_wait(_cid, **_kwargs):
            return 1

        async def fake_transition(_sid, target, **fields):
            transitions.append((target, fields))
            return True

        async def fake_event(_sid, _kind, payload):
            events.append(payload)

        async def noop(*_args, **_kwargs):
            return None

        events: list = []
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.ROW))
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The claim to finalizing comes first; the failure lands on the
        # terminal transition from there.
        assert transitions[0][0] is SessionStatus.FINALIZING
        target, fields = transitions[1]
        assert target is SessionStatus.FAILED
        assert "finalization failed" in fields["error"]
        assert events[0]["status"] == "failed"

    async def test_a_finalizing_row_still_reaches_the_finalizer(self, monkeypatch, tmp_path):
        # Restart recovery hands a finalizing row back to settlement with a
        # clean exit: the finalizer must still run — it is idempotent, so a
        # second run either completes the push or reports a real failure —
        # and no second claim is attempted: the row is already finalizing.
        from app import sessions

        self._patch_base(monkeypatch, tmp_path)
        created: list = []
        transitions: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-finalize"

        async def fake_wait(_cid, **_kwargs):
            return 0

        async def fake_transition(_sid, target, **_fields):
            transitions.append(target)
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value({**self.ROW, "status": "finalizing"}))
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert len(created) == 1
        assert created[0]["name"] == "logos-agent-finalize-7"
        # Only the terminal transition: no re-claim of a state the row
        # already has.
        assert transitions == [SessionStatus.SUCCEEDED]

    async def test_a_scheduler_pass_cannot_pause_a_finalizing_session(self, monkeypatch, tmp_path):
        # The agent exited cleanly and settlement claimed finalizing before
        # the finalizer started; the agent container is gone. A high-load
        # scheduler pass must not move the row to paused: the pause would
        # hit an exited container (Docker's 409 ignored), and a later
        # resume would return the row to running with no supervisor left to
        # finish it — stranding the session. The row leaves the running set
        # with the claim, so the pass has nothing to pause; a pause that
        # raced the claim loses the transition, and the session still
        # settles.
        from app import capacity, sessions
        from app.schemas import can_transition

        self._patch_base(monkeypatch, tmp_path)
        # A fresh manager: the module singleton's admission lock binds to
        # whichever loop first contended on it.
        manager = sessions.SessionManager()
        monkeypatch.setattr(sessions, "manager", manager)

        states = {7: "running"}
        order: list = []
        paused: list = []
        events: list = []

        async def fake_reading(_timeout_s=5.0, lane=None, ours=None):
            return capacity.Reading(load=0.99, busy_slots=10, total_slots=10, queue_total=0, ok=True)

        async def fake_in_status(status):
            # A fresh read on every call, like the database.
            return [dict(self.ROW)] if states[7] == status.value else []

        async def fake_transition(sid, target, **_fields):
            order.append(("transition", target))
            # A validated transition, like the database: only legal edges,
            # and the row really moves.
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        async def fake_finalize(_self, _sid):
            order.append(("finalize", "start"))
            # The platform spikes while the finalizer runs: a full pass,
            # plus a pause that read the running row before the claim and
            # lands anyway.
            await manager.scheduler_pass()
            await manager._pause(dict(self.ROW), "load")
            order.append(("finalize", "end"))
            return True

        async def fake_pause(cid, **_kwargs):
            # Docker really froze it: the race this test is about is the one
            # the database then decides, not a pause Docker refused.
            paused.append(cid)
            return True

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", fake_reading)
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.ROW))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "pause_container", fake_pause)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.SessionManager, "_finalize", fake_finalize)

        await manager._settle(7, exit_code=0, error=None)

        # The claim came first, the pass ran while the row was finalizing,
        # and the row still reached its terminal state.
        assert order[0] == ("transition", SessionStatus.FINALIZING)
        assert ("finalize", "start") in order and ("finalize", "end") in order
        assert states[7] == "succeeded"
        # The racing pause did reach Docker (409 on the exited container,
        # ignored in production) and did attempt the transition — but the
        # state machine refused it: the row went straight from finalizing
        # to its terminal state, no pause event was emitted, and the
        # session was not left stranded.
        assert paused == ["cid-7"]
        assert ("transition", SessionStatus.PAUSED) in order
        assert events == [(EventKind.STATUS, {"status": "succeeded", "exit_code": 0, "error": None})]

    async def test_a_cancel_while_finalizing_stops_the_finalizer_helper(self, monkeypatch, tmp_path):
        # A finalizing session still holds the credential-bearing helper
        # container — the one committing, pushing, and opening the pull
        # request with the scoped token. A cancel must stop that helper
        # before it reports success: returning success while the helper
        # keeps running would leave a container with the push token acting
        # on a session the API already reported as cancelled. The helper is
        # tracked per session (not read from a supervisor, which restart
        # reconciliation does not run one), so the stop reaches it on both
        # the supervised and the reconciled path.
        from app import sessions
        from app.schemas import can_transition

        self._patch_base(monkeypatch, tmp_path)
        # A fresh manager: the module singleton's locks bind to whichever
        # loop first contended on them.
        manager = sessions.SessionManager()

        states = {7: "running"}
        events: list = []
        stopped: list = []
        removed: list = []
        created: list = []
        wait_calls: list = []
        helper_wait = asyncio.Event()

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-finalize"

        async def fake_wait(cid, **_kwargs):
            wait_calls.append(cid)
            if cid == "cid-finalize":
                await helper_wait.wait()
                return 1
            return 0

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)
            if cid == "cid-finalize":
                helper_wait.set()

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_get_session(_sid):
            return {**self.ROW, "status": states[7]}

        async def fake_transition(sid, target, **_fields):
            # A validated transition, like the database: only legal edges,
            # and the row really moves.
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", fake_get_session)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))

        settle = asyncio.create_task(manager._settle(7, exit_code=0, error=None))
        try:
            # Wait until the finalizer helper exists and is being awaited.
            for _ in range(100):
                if "cid-finalize" in wait_calls:
                    break
                await asyncio.sleep(0.01)
            assert "cid-finalize" in wait_calls
            helper = manager._helpers.get(7)
            assert helper is not None and helper.container_id == "cid-finalize"

            # Cancel while the helper is still running.
            assert await manager.cancel(7) is True
            # The success means the helper was already stopped: it held the
            # push token, so it must not outlive the reported cancellation.
            assert "cid-finalize" in stopped
        finally:
            helper_wait.set()
            await settle

        # The row is cancelled and stays there: the settlement that lost the
        # race records nothing (no succeeded/failed event, no deploy), and
        # the helper that ran it removed its own container on the way out.
        assert states[7] == "cancelled"
        assert [p["status"] for k, p in events if k == EventKind.STATUS] == ["cancelled"]
        assert "cid-finalize" in removed
        assert 7 not in manager._helpers
        # The helper ran as a finalizer, not something else.
        assert created and created[-1]["labels"] == {"logos.agent.helper": "finalize"}

    async def test_a_cancel_inside_the_prepare_helper_start_window_stops_the_helper(self, monkeypatch, tmp_path):
        # The prepare helper is the exposed path: while it runs, the row is
        # still 'starting' with no persisted container id, and no
        # supervisor exists yet. The helper container holds the push token
        # from the moment it is created, so a cancel that lands inside its
        # create-to-start window must find it in the helper map and stop
        # it — the registration happens before the start returns, not
        # after, and the launch that loses the race records nothing.
        #
        # The stop must also run against a settled start: a stop that lands
        # before the in-flight start has completed is a 304 no-op, and the
        # start would then complete and leave a credential-bearing
        # container running with no one tracking it. So the cancel waits
        # for the start, then stops and removes before reporting success.
        from app import sessions
        from app.schemas import can_transition

        self._patch_base(monkeypatch, tmp_path)
        # A fresh manager: the module singleton's locks bind to whichever
        # loop first contended on them.
        manager = sessions.SessionManager()

        states = {7: "starting"}
        row = {**self.ROW, "status": "starting", "container_id": None}
        # The fake daemon: the start is what actually brings the container
        # up, a stop only works once it is running (stop-before-start is a
        # 304 no-op), and the wait returns only when the container is out.
        docker: dict = {"started": False, "running": False, "removed": False}
        order: list = []
        events: list = []
        created: list = []
        start_entered = asyncio.Event()
        start_go = asyncio.Event()
        stopped = asyncio.Event()

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-prepare"

        async def fake_start(cid):
            if cid == "cid-prepare":
                # A slow start: the window in which the container exists
                # and is starting but the cancel is still allowed to land.
                start_entered.set()
                await start_go.wait()
            docker["started"] = True
            docker["running"] = True
            order.append("start")

        async def fake_wait(cid, **_kwargs):
            # The container exits when it is stopped or removed.
            await stopped.wait()
            return 137

        async def fake_stop(cid, **_kwargs):
            order.append("stop")
            if docker["started"] and docker["running"]:
                docker["running"] = False
                stopped.set()
            # else: 304 — nothing running to stop, nothing happens.

        async def fake_remove(cid, **_kwargs):
            order.append("remove")
            docker["removed"] = True
            docker["running"] = False
            stopped.set()

        async def fake_get_session(_sid):
            return {**row, "status": states[7]}

        async def fake_transition(sid, target, **_fields):
            # A validated transition, like the database: only legal edges,
            # and the row really moves.
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "get_session", fake_get_session)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        launch = asyncio.create_task(manager._launch(self.SESSION))
        try:
            # The prepare helper's start is in flight: the container exists
            # and is starting, the row is still 'starting' with no stored
            # container id, and there is no supervisor.
            await start_entered.wait()

            # The helper is already tracked before its start returns, so
            # the cancel that lands here has a container to stop.
            helper = manager._helpers.get(7)
            assert helper is not None and helper.container_id == "cid-prepare"

            cancel_task = asyncio.create_task(manager.cancel(7))
            # The cancel pops the in-flight helper ...
            for _ in range(100):
                if 7 not in manager._helpers:
                    break
                await asyncio.sleep(0.01)
            # ... and must not have reported success yet: the start has
            # not settled, so a stop now would be a 304 no-op.
            assert not cancel_task.done()

            # The start now completes after the cancel has popped the
            # helper — the ordering the 304 race is about.
            start_go.set()
            assert await cancel_task is True
            # The stop ran against the settled start, not before it, and
            # the success means the container is stopped and gone — not
            # merely that a stop was invoked.
            assert order.index("start") < order.index("stop")
            assert docker["running"] is False
            assert docker["removed"] is True
        finally:
            start_go.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(launch, timeout=1)

        # The launch that lost the race to the cancel records nothing: no
        # running status, no supervision of a cancelled session.
        assert states[7] == "cancelled"
        assert [p["status"] for k, p in events if k == EventKind.STATUS] == ["cancelled"]
        assert 7 not in manager._supervisors
        assert created and created[0]["labels"] == {"logos.agent.helper": "prepare"}

    async def test_a_cancel_inside_the_prepare_helper_create_window_stops_the_helper(self, monkeypatch, tmp_path):
        # One step earlier than the start window: the create request
        # itself. While the POST is in flight no container exists yet —
        # but it holds the push token the moment the request returns. The
        # helper is therefore tracked from before the create, a cancel that
        # lands inside the request waits for it to settle, and the
        # returned container is stopped and removed instead of being
        # started — only then does the cancel report success.
        from app import sessions
        from app.schemas import can_transition

        self._patch_base(monkeypatch, tmp_path)
        # A fresh manager: the module singleton's locks bind to whichever
        # loop first contended on them.
        manager = sessions.SessionManager()

        states = {7: "starting"}
        row = {**self.ROW, "status": "starting", "container_id": None}
        # The fake daemon: the create POST is the delayed one, the start
        # is what would bring the container up, and a stop only works once
        # it is running (stop-before-start is a 304 no-op).
        docker: dict = {"running": False, "removed": False}
        order: list = []
        events: list = []
        created: list = []
        create_entered = asyncio.Event()
        create_go = asyncio.Event()
        stopped = asyncio.Event()

        async def fake_create(**kwargs):
            created.append(kwargs)
            # A slow create: the window in which the request is in flight
            # and the cancel is still allowed to land.
            create_entered.set()
            await create_go.wait()
            order.append("create")
            return "cid-prepare"

        async def fake_start(cid):
            order.append("start")
            docker["running"] = True

        async def fake_wait(cid, **_kwargs):
            # The container exits when it is stopped or removed.
            await stopped.wait()
            return 137

        async def fake_stop(cid, **_kwargs):
            order.append("stop")
            if docker["running"]:
                docker["running"] = False
                stopped.set()
            # else: 304 — never running, nothing to stop.

        async def fake_remove(cid, **_kwargs):
            order.append("remove")
            docker["removed"] = True
            docker["running"] = False
            stopped.set()

        async def fake_get_session(_sid):
            return {**row, "status": states[7]}

        async def fake_transition(sid, target, **_fields):
            # A validated transition, like the database: only legal edges,
            # and the row really moves.
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "get_session", fake_get_session)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        launch = asyncio.create_task(manager._launch(self.SESSION))
        try:
            # The prepare helper's create is in flight: no container exists
            # yet, the row is still 'starting' with no stored container
            # id, and there is no supervisor.
            await create_entered.wait()

            # The fix itself: the helper is already tracked while its
            # create is in flight — a record without a container id yet.
            helper = manager._helpers.get(7)
            assert helper is not None and helper.container_id is None

            cancel_task = asyncio.create_task(manager.cancel(7))
            # The cancel pops the in-flight helper ...
            for _ in range(100):
                if 7 not in manager._helpers:
                    break
                await asyncio.sleep(0.01)
            # ... and must not have reported success yet: the create has
            # not settled, so the container is not known to exist or not.
            assert not cancel_task.done()

            # The create now returns a container id after the cancel has
            # popped the helper — the ordering this race is about.
            create_go.set()
            assert await cancel_task is True
            # The returned container was never started and is gone; the
            # stop is the 304 against a container that never ran.
            assert "start" not in order
            assert docker["running"] is False
            assert docker["removed"] is True
            assert "stop" in order and "remove" in order
        finally:
            create_go.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(launch, timeout=1)

        # The launch that lost the race to the cancel records nothing: no
        # running status, no supervision of a cancelled session.
        assert states[7] == "cancelled"
        assert [p["status"] for k, p in events if k == EventKind.STATUS] == ["cancelled"]
        assert 7 not in manager._supervisors
        assert created and created[0]["labels"] == {"logos.agent.helper": "prepare"}

    async def test_a_cancel_before_the_prepare_helper_starts_nothing(self, monkeypatch, tmp_path):
        # One step earlier again: the launch has not reached any container
        # yet — it is resolving the workspace volume and the artefact
        # mountpoint. Nothing is tracked in _helpers or _supervisors there,
        # so a cancel used to report success and leave the resumed launch to
        # run the credential-bearing prepare helper and start the agent
        # anyway. The launch is now tracked from before its first await and
        # observes the cancellation at its next boundary.
        from app import sessions
        from app.schemas import can_transition

        self._patch_base(monkeypatch, tmp_path)
        manager = sessions.SessionManager()

        states = {7: "starting"}
        row = {**self.ROW, "status": "starting", "container_id": None}
        created: list = []
        events: list = []
        mountpoint_entered = asyncio.Event()
        mountpoint_go = asyncio.Event()

        async def slow_mountpoint(_volume):
            # The pre-container stretch of the launch: no helper, no
            # supervisor, no container id anywhere.
            mountpoint_entered.set()
            await mountpoint_go.wait()
            return "/vol/data"

        async def fake_create(**kwargs):
            created.append(kwargs)
            return f"cid-{len(created)}"

        async def fake_transition(sid, target, **_fields):
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.db, "update_session", noop)
        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", slow_mountpoint)
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(
            sessions.model_policy,
            "current",
            lambda: sessions.model_policy.ModelPolicy(
                local_models=frozenset({"local-model"}),
                offered=("local-model",),
                ok=True,
                unknown=False,
            ),
        )

        launch = asyncio.create_task(manager._launch(self.SESSION))
        try:
            await mountpoint_entered.wait()
            # Nothing a cancel could previously have found — but the launch
            # itself is tracked.
            assert 7 not in manager._helpers
            assert 7 not in manager._supervisors
            assert 7 in manager._launches

            cancel_task = asyncio.create_task(manager.cancel(7))
            # Let the cancel claim the row and mark the launch.
            for _ in range(100):
                if 7 not in manager._launches:
                    break
                await asyncio.sleep(0.01)
            # The launch resumes into a cancelled session.
            mountpoint_go.set()
            assert await asyncio.wait_for(cancel_task, timeout=2) is True
        finally:
            mountpoint_go.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(launch, timeout=2)

        # The point of the fix: no prepare helper ran, so the push token
        # never entered a container, and no agent was started for a session
        # the API reported cancelled.
        assert created == []
        assert states[7] == "cancelled"
        assert [p["status"] for k, p in events if k == EventKind.STATUS] == ["cancelled"]
        assert 7 not in manager._supervisors


class TestYieldingReallyYields:
    """Pausing has to return the serving slot, not just stop the client.

    A frozen process does not cancel the generation it already started and
    does not close its socket, so the slot stays occupied for the length of
    the pause unless the connection is taken down.
    """

    ROW = {"id": 7, "container_id": "cid-7"}

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_a_paused_session_is_cut_off_from_the_model_gateway(self, monkeypatch):
        from app import sessions

        order: list = []

        async def fake_pause(cid, **_kwargs):
            order.append(("pause", cid))
            return True

        async def fake_disconnect(network, cid):
            order.append(("disconnect", network, cid))
            return True

        async def fake_transition(_sid, _target, **_fields):
            order.append(("transition", _target))
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "pause_container", fake_pause)
        monkeypatch.setattr(sessions.docker_engine, "disconnect_network", fake_disconnect)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.SessionManager()._pause(self.ROW, "users are queueing")

        # Frozen first, then cut off: a container that can still run would
        # notice the network error and retry into the load we are yielding.
        assert order[0] == ("pause", "cid-7")
        assert order[1] == ("disconnect", sessions.settings.session_network, "cid-7")
        assert ("transition", SessionStatus.PAUSED) in order

    async def test_a_pause_docker_refused_does_not_move_the_row(self, monkeypatch):
        from app import sessions

        transitions: list = []

        async def refused(_cid, **_kwargs):
            return False

        async def fake_transition(_sid, target, **_fields):
            transitions.append(target)
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "pause_container", refused)
        monkeypatch.setattr(sessions.docker_engine, "disconnect_network", noop)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.SessionManager()._pause(self.ROW, "users are queueing")

        # The agent exited in the window between the scheduler's reading and
        # the pause. A row moved to 'paused' around a gone container could
        # never be settled; leaving it alone lets its supervisor finish it.
        assert transitions == []

    async def test_a_resumed_session_is_reattached_before_it_is_thawed(self, monkeypatch):
        from app import sessions

        order: list = []

        async def fake_connect(network, cid):
            order.append(("connect", network, cid))
            return True

        async def fake_unpause(cid, **_kwargs):
            order.append(("unpause", cid))
            return True

        async def fake_transition(_sid, target, **_fields):
            order.append(("transition", target))
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "connect_network", fake_connect)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", fake_unpause)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.SessionManager()._resume(self.ROW, "load dropped")

        assert order[0] == ("connect", sessions.settings.session_network, "cid-7")
        assert order[1] == ("unpause", "cid-7")
        assert ("transition", SessionStatus.RUNNING) in order

    async def test_a_session_that_cannot_be_reattached_stays_paused(self, monkeypatch):
        from app import sessions

        unpaused: list = []
        transitions: list = []

        async def failing_connect(_network, _cid):
            return False

        async def fake_unpause(cid, **_kwargs):
            unpaused.append(cid)
            return True

        async def fake_transition(_sid, target, **_fields):
            transitions.append(target)
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "connect_network", failing_connect)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", fake_unpause)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.SessionManager()._resume(self.ROW, "load dropped")

        # Thawing a session that cannot reach the gateway would only fail its
        # next model call; one more paused tick costs nothing.
        assert unpaused == []
        assert transitions == []


class TestClaimToLaunchWindow:
    """The stretch between claiming a queued row and launching it.

    `scheduler_pass` claims the row, writes a capacity event, and only then
    launches. That event write is an await: a cancel landing in it must not
    be overtaken by a launch that never learned of it.
    """

    async def test_a_cancel_between_the_claim_and_the_launch_starts_nothing(self, monkeypatch, tmp_path):
        from app import capacity, sessions
        from app.schemas import can_transition

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        manager = sessions.SessionManager()

        states = {5: "queued"}
        session_row = {"id": 5, "workspace_id": 1, "task": "a long enough task", "model": None}
        created: list = []
        event_entered = asyncio.Event()
        event_go = asyncio.Event()

        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=4, queue_total=0, ok=True)

        async def fake_claim(_limit, *, include_triggered: bool = True):
            states[5] = "starting"
            return [session_row]

        async def slow_event(_sid, _kind, _payload):
            # The window: the row is claimed, the launch has not begun.
            event_entered.set()
            await event_go.wait()

        async def fake_transition(sid, target, **_fields):
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-should-not-exist"

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", self._async_value(reading))
        monkeypatch.setattr(sessions.db, "sessions_in_status", self._async_value([]))
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "claim_session", _claim_one(fake_claim))
        monkeypatch.setattr(sessions.db, "next_queued_session", _peek)
        monkeypatch.setattr(sessions.db, "add_event", slow_event)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value({**session_row, "status": "starting"}))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "get_workspace", self._async_value(self.WORKSPACE))
        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", noop)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        pass_task = asyncio.create_task(manager.scheduler_pass())
        try:
            await event_entered.wait()
            # The claim already registered the launch, which is what the
            # cancel needs to find.
            assert 5 in manager._launches

            cancel_task = asyncio.create_task(manager.cancel(5))
            for _ in range(100):
                if manager._launches.get(5) is not None and manager._launches[5].cancelled:
                    break
                await asyncio.sleep(0.01)
            event_go.set()
            assert await asyncio.wait_for(cancel_task, timeout=2) is True
        finally:
            event_go.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(pass_task, timeout=2)

        # No container of any kind: not the prepare helper that would have
        # held the push token, not the agent.
        assert created == []
        assert states[5] == "cancelled"

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    WORKSPACE = {
        "id": 1,
        "name": "feature-work",
        "base_branch": "main",
        "volume_name": "logos-agent-ws-1",
    }


class TestOverlappingAdmission:
    """Admission under overlapping scheduler passes.

    Every session creation schedules a pass, so passes overlap. The room
    must be computed from counts read inside the admission lock, after any
    earlier pass has launched its batch — otherwise each pass admits a full
    batch from the same stale snapshot and the parallel ceiling is exceeded.
    """

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_overlapping_passes_cannot_exceed_the_parallel_ceiling(self, monkeypatch, tmp_path):
        from app import capacity, sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), max_parallel_sessions=2),
        )
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=1, queue_total=0, ok=True)
        states = {sid: "queued" for sid in (1, 2, 3, 4)}
        queue = [{"id": sid, "workspace_id": sid} for sid in states]
        launched: list = []

        async def fake_in_status(status):
            # Always a fresh read, like the database: whatever is true now.
            return [{"id": sid, "workspace_id": sid} for sid, state in states.items() if state == status.value]

        async def fake_claim(limit, *, include_triggered: bool = True):
            claimed = []
            while limit > 0 and queue:
                session = queue.pop(0)
                states[session["id"]] = "starting"
                claimed.append(session)
                limit -= 1
            return claimed

        async def fake_launch(_self, session):
            # Like the real launch, the row becomes running while the
            # admission lock is still held.
            await asyncio.sleep(0)
            states[session["id"]] = "running"
            launched.append(session["id"])

        async def fake_event(_sid, _kind, _payload):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", self._async_value(reading))
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "claim_session", _claim_one(fake_claim))
        monkeypatch.setattr(sessions.db, "next_queued_session", _peek)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.SessionManager, "_launch", fake_launch)

        await asyncio.gather(sessions.manager.scheduler_pass(), sessions.manager.scheduler_pass())

        # The ceiling is two: the second pass must see the first one's
        # launches and find no room, not admit another full batch.
        assert sorted(launched) == [1, 2]

    async def test_one_fresh_reading_admits_at_most_one_session(self, monkeypatch, tmp_path):
        # A single below-threshold reading must not claim every open slot:
        # a whole batch admitted at once would move a small fleet from zero
        # load to occupying (or queueing for) every loaded slot before the
        # next observation can notice. One fresh reading admits one
        # session; the rest wait for the next pass's own observation.
        from app import capacity, sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), max_parallel_sessions=4),
        )
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=1, queue_total=0, ok=True)
        states = {sid: "queued" for sid in (1, 2, 3, 4)}
        queue = [{"id": sid, "workspace_id": sid} for sid in states]
        launched: list = []

        async def fake_in_status(status):
            return [{"id": sid, "workspace_id": sid} for sid, state in states.items() if state == status.value]

        async def fake_claim(limit, *, include_triggered: bool = True):
            claimed = []
            while limit > 0 and queue:
                session = queue.pop(0)
                states[session["id"]] = "starting"
                claimed.append(session)
                limit -= 1
            return claimed

        async def fake_launch(_self, session):
            # Like the real launch, the row becomes running while the
            # admission lock is still held.
            await asyncio.sleep(0)
            states[session["id"]] = "running"
            launched.append(session["id"])

        async def fake_event(_sid, _kind, _payload):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", self._async_value(reading))
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "claim_session", _claim_one(fake_claim))
        monkeypatch.setattr(sessions.db, "next_queued_session", _peek)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.SessionManager, "_launch", fake_launch)

        await sessions.manager.scheduler_pass()

        # One fresh reading, one admission: the other three stay queued for
        # the next pass's own capacity observation.
        assert launched == [1]
        assert [sid for sid, state in states.items() if state == "queued"] == [2, 3, 4]

    async def test_overlapping_passes_cannot_share_one_pre_launch_reading(self, monkeypatch, tmp_path):
        # Creation-triggered passes overlap: a pass that sampled the load
        # before an earlier pass's launch must not admit against that stale
        # sample — a burst of such passes could each claim one session from
        # the same pre-launch load and fill the ceiling without a single
        # observation made after any of the launches. The reading that
        # gates a claim must be taken after the admission lock is held.
        from app import capacity, sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), max_parallel_sessions=4),
        )
        idle = capacity.Reading(load=0.0, busy_slots=0, total_slots=10, queue_total=0, ok=True)
        # At or above the start threshold, below the pause threshold: the
        # platform has work, but nothing to interrupt.
        busy = capacity.Reading(load=0.7, busy_slots=7, total_slots=10, queue_total=0, ok=True)
        # The fleet is idle until the first launch has taken its effect,
        # after which no further admission is justified.
        readings = [idle, idle, busy, busy, busy]
        decided_loads: list = []
        real_start_decision = capacity.start_decision

        async def fake_read_load(lane=None, ours=None):
            # A pass takes two readings of one moment — the platform's, and
            # the platform's minus this runner's share — so only the first
            # of the pair advances the prepared sequence.
            if ours is None and len(readings) > 1:
                return readings.pop(0)
            return readings[0]

        def spy_start_decision(reading, **kwargs):
            decided_loads.append(reading.load)
            return real_start_decision(reading, **kwargs)

        states = {sid: "queued" for sid in (1, 2, 3, 4)}
        queue = [{"id": sid, "workspace_id": sid} for sid in states]
        launched: list = []

        async def fake_in_status(status):
            return [{"id": sid, "workspace_id": sid} for sid, state in states.items() if state == status.value]

        async def fake_claim(limit, *, include_triggered: bool = True):
            claimed = []
            while limit > 0 and queue:
                session = queue.pop(0)
                states[session["id"]] = "starting"
                claimed.append(session)
                limit -= 1
            return claimed

        async def fake_launch(_self, session):
            # The launch takes time on the real engine; the row becomes
            # running while the admission lock is still held.
            await asyncio.sleep(0)
            states[session["id"]] = "running"
            launched.append(session["id"])

        async def fake_event(_sid, _kind, _payload):
            return None

        monkeypatch.setattr(sessions.capacity, "read_load", fake_read_load)
        monkeypatch.setattr(sessions.capacity, "start_decision", spy_start_decision)
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "claim_session", _claim_one(fake_claim))
        monkeypatch.setattr(sessions.db, "next_queued_session", _peek)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.SessionManager, "_launch", fake_launch)
        # A fresh manager: the shared singleton's admission lock is bound to
        # whichever test's event loop first contended on it, and the passes
        # here do contend — on this test's new loop that would raise.
        monkeypatch.setattr(sessions, "manager", sessions.SessionManager())

        await asyncio.gather(sessions.manager.scheduler_pass(), sessions.manager.scheduler_pass())

        # The second pass's own reading already sees the load the first
        # pass's launch caused, so it admits nothing: one pre-launch sample
        # bought exactly one session, not one per overlapping pass.
        assert launched == [1]
        assert [sid for sid, state in states.items() if state == "queued"] == [2, 3, 4]
        # And the second decision was made on a post-launch observation, not
        # on the shared pre-launch one.
        assert decided_loads[0] == 0.0
        assert decided_loads[1] > 0.0


class TestScreenshotOrchestration:
    """Where and when the requested dev pages get photographed.

    The screenshots must show the revision the session just deployed, so they
    are taken by the runner during settlement — after the deploy dispatch and
    only once the environment serves again — never from inside the session
    container, which exits before any of that happens.
    """

    SESSION_ROW = {
        "status": "running",
        "container_id": "cid-7",
        "deploy_to_dev": False,
        "branch_name": "agent/feature-work/session-7",
        "screenshot_paths": ["/dashboard", "/models"],
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path, *, deploy_enabled=False):
        from app import sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), deploy_enabled=deploy_enabled),
        )
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol/data"))
        monkeypatch.setattr(sessions.db, "update_session", self._async_value(None))
        # These tests settle sessions directly; the finalizer is the
        # runner's job in the real flow and is covered on its own.
        monkeypatch.setattr(sessions.SessionManager, "_finalize", self._async_value(True))
        return sessions

    async def test_screenshots_are_captured_in_settlement_without_a_deploy(self, monkeypatch, tmp_path):
        from app import sessions

        self._patch_base(monkeypatch, tmp_path)
        created: list = []
        removed: list = []
        events: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return f"cid-shot-{len(created)}"

        async def fake_wait(_cid, **_kwargs):
            return 0

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_start(_cid):
            return None

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._settle(7, exit_code=0, error=None)

        base = sessions.settings.dev_base_url.rstrip("/")
        # One one-shot container per requested page, pointed at the session's
        # own artefact directory, and each removed afterwards.
        assert [c["url"] for c in created] == [f"{base}/dashboard", f"{base}/models"]
        assert [c["output_path"] for c in created] == [
            "/artifacts/screenshots/00-dashboard.png",
            "/artifacts/screenshots/01-models.png",
        ]
        assert all(c["artifact_host_path"] == "/vol/data/7" for c in created)
        assert removed == ["cid-7", "cid-shot-1", "cid-shot-2"]
        names = [p["name"] for k, p in events if k == EventKind.SCREENSHOT]
        assert names == ["00-dashboard.png", "01-models.png"]

    async def test_screenshots_wait_for_a_dispatched_deploy_to_finish(self, monkeypatch, tmp_path):
        from app import sessions

        self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        row = {**self.SESSION_ROW, "deploy_to_dev": True, "screenshot_paths": ["/dashboard"]}
        result = tmp_path / "7"
        result.mkdir(parents=True, exist_ok=True)
        (result / "result.json").write_text(
            json.dumps(
                {
                    "pr_url": "https://github.com/ls1intum/edutelligence/pull/772",
                    "pushed_sha": "f" * 40,
                }
            )
        )
        order: list = []
        created: list = []
        wait_calls: list = []

        async def fake_build_wait(_branch, _sha, **_kwargs):
            return "success", "build ended: success"

        async def fake_marker():
            order.append("marker")
            return 40

        async def fake_dispatch(**_kwargs):
            order.append("dispatch")
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_wait(**kwargs):
            order.append("wait")
            wait_calls.append(kwargs)
            return "success", "run ended: success"

        async def fake_ready(_self):
            order.append("ready")
            return True

        async def fake_create(**kwargs):
            order.append("screenshot")
            created.append(kwargs)
            return "cid-shot"

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_dev_deploy", fake_wait)
        monkeypatch.setattr(sessions.SessionManager, "_wait_dev_ready", fake_ready)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", self._async_value(0))
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", noop)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The strict point of this fix: the photo comes only after the deploy
        # has been dispatched, waited out, and the environment serves again.
        # The marker is recorded before the dispatch — the run the dispatch
        # creates is the one that turns out newer than it.
        assert order == ["marker", "dispatch", "wait", "ready", "screenshot"]
        # The wait is handed the marker: it may settle only a run of the
        # deploy workflow newer than what existed before the dispatch, never
        # a deploy that predates it.
        assert wait_calls == [{"after_run_id": 40}]
        assert created[0]["url"].endswith("/dashboard")

    async def test_screenshots_are_skipped_when_the_deploy_does_not_succeed(self, monkeypatch, tmp_path):
        from app import sessions

        self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        row = {**self.SESSION_ROW, "deploy_to_dev": True}
        result = tmp_path / "7"
        result.mkdir(parents=True, exist_ok=True)
        (result / "result.json").write_text(
            json.dumps(
                {
                    "pr_url": "https://github.com/ls1intum/edutelligence/pull/772",
                    "pushed_sha": "f" * 40,
                }
            )
        )
        events: list = []
        created: list = []

        async def fake_build_wait(_branch, _sha, **_kwargs):
            return "success", "build ended: success"

        async def fake_marker():
            return 40

        async def fake_dispatch(**_kwargs):
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_wait(**_kwargs):
            return "timeout", "still running after 1200s"

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-shot"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_dev_deploy", fake_wait)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # A deploy that did not succeed means nothing was deployed; a photo
        # of the old revision would be worse than no photo.
        assert created == []
        skipped = [p for k, p in events if k == EventKind.SCREENSHOT and p.get("status") == "skipped"]
        assert len(skipped) == 1
        assert "did not succeed" in skipped[0]["reason"]

    async def test_concurrent_deploys_do_not_interleave_the_environment_sequence(self, monkeypatch, tmp_path):
        # The dev environment is shared by every session on the runner, so
        # the sequences that change it and then observe it — dispatch, wait
        # for the run that dispatch created, wait for the environment to
        # serve, take the photos — must not interleave across sessions: an
        # interleaved pair would each settle against the other's run and
        # photograph the other's revision.
        from app import sessions

        self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        for sid in (7, 8):
            directory = tmp_path / str(sid)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "result.json").write_text(
                json.dumps(
                    {
                        "pr_url": f"https://github.com/ls1intum/edutelligence/pull/{sid}",
                        "pushed_sha": "f" * 40,
                    }
                )
            )
        order: list = []

        async def fake_get_session(_sid):
            return {
                "status": "running",
                "container_id": "cid-x",
                "deploy_to_dev": True,
                "branch_name": "agent/feature-work/session",
                "screenshot_paths": ["/dashboard"],
            }

        async def fake_build_wait(_branch, _sha, **_kwargs):
            return "success", "build ended: success"

        async def fake_marker():
            return 40

        async def fake_dispatch(**_kwargs):
            order.append("dispatch")
            # Yield so the other settling session can run while this one is
            # inside the environment sequence — only the lock keeps it out.
            await asyncio.sleep(0)
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_wait(**_kwargs):
            order.append("wait")
            await asyncio.sleep(0)
            return "success", "run ended: success"

        async def fake_ready(_self):
            order.append("ready")
            await asyncio.sleep(0)
            return True

        async def fake_create(**_kwargs):
            order.append("screenshot")
            await asyncio.sleep(0)
            return "cid-shot"

        async def fake_transition(_sid, _target, **_fields):
            return True

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", fake_get_session)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_dev_deploy", fake_wait)
        monkeypatch.setattr(sessions.SessionManager, "_wait_dev_ready", fake_ready)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "start_container", noop)
        monkeypatch.setattr(sessions.docker_engine, "wait_container", self._async_value(0))
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await asyncio.gather(
            sessions.manager._settle(7, exit_code=0, error=None),
            sessions.manager._settle(8, exit_code=0, error=None),
        )

        # One dispatch-to-screenshot block per session, and the blocks do not
        # interleave: each sequence ran to completion before the next began.
        assert order == ["dispatch", "wait", "ready", "screenshot"] * 2

    async def test_screenshots_are_skipped_when_the_requested_deploy_did_not_land(self, monkeypatch, tmp_path):
        # The session asked for a deploy and it did not land (here: refused,
        # because no pull request was opened and no image of the branch
        # exists). The environment still serves the previous revision, so a
        # photo attributed to this session would document the old code.
        sessions = self._patch_base(monkeypatch, tmp_path, deploy_enabled=True)
        row = {**self.SESSION_ROW, "deploy_to_dev": True}
        events: list = []
        created: list = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid-shot"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            raise AssertionError("no image exists to dispatch a deploy of")

        async def fake_build_wait(_branch, _sha, **_kwargs):
            raise AssertionError("no image exists to wait for")

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(row))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "create_screenshot_container", fake_create)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        # No result file, hence no pull request: the deploy is refused and
        # the photos are skipped with it.
        await sessions.manager._settle(7, exit_code=0, error=None)

        assert created == []
        skipped = [p for k, p in events if k == EventKind.SCREENSHOT and p.get("status") == "skipped"]
        assert len(skipped) == 1
        assert "did not land" in skipped[0]["reason"]


class TestSettlementRaceAndDeployTag:
    """Settlement against a lost transition, and the tag a deploy pulls.

    Two races the state machine has to lose cleanly: a cancel that reaches
    the terminal row before settlement does, and a dispatch that would pull
    ``latest`` — which still points at main — instead of the pull request
    build that actually contains the session's code.
    """

    SESSION_ROW = {
        "status": "running",
        "container_id": "cid-7",
        "deploy_to_dev": True,
        "branch_name": "agent/feature-work/session-7",
        "screenshot_paths": [],
    }

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(
            sessions,
            "settings",
            replace(sessions.settings, artifact_root=str(tmp_path), deploy_enabled=True),
        )
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        monkeypatch.setattr(sessions.db, "update_session", self._async_value(None))
        # These tests settle sessions directly; the finalizer is the
        # runner's job in the real flow and is covered on its own.
        monkeypatch.setattr(sessions.SessionManager, "_finalize", self._async_value(True))
        return sessions

    def _write_result(self, tmp_path, **payload):
        directory = tmp_path / "7"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "result.json").write_text(json.dumps(payload))

    async def test_settlement_losing_to_a_cancel_runs_no_side_effects(self, monkeypatch, tmp_path):
        # An operator can cancel while restart reconciliation settles an
        # exited container. The cancel moves the row to CANCELLED first, so
        # the settlement's terminal transition returns False: it must still
        # remove the container, but must not emit a status event, dispatch a
        # deploy, or take screenshots for a session that is already final.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(tmp_path, pr_url="https://github.com/ls1intum/edutelligence/pull/772")
        removed: list = []
        events: list = []
        dispatched: list = []
        build_waits: list = []

        async def fake_transition(_sid, _target, **_fields):
            return False

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_build_wait(branch, sha, **_kwargs):
            build_waits.append((branch, sha))
            return "success", "build ended: success"

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The container is given back, but the row belongs to the cancel:
        # no succeeded/failed event, no deploy, no build wait — even though
        # the result file carries a pull request.
        assert removed == ["cid-7"]
        assert events == []
        assert dispatched == []
        assert build_waits == []

    async def test_deploy_waits_for_the_pr_build_and_uses_its_tag(self, monkeypatch, tmp_path):
        # The result carries the PR URL, so the deploy must wait for the
        # pr-<n> build to succeed and dispatch with exactly that tag — never
        # latest, which still points at main.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(
            tmp_path,
            pr_url="https://github.com/ls1intum/edutelligence/pull/772",
            pushed_sha="f" * 40,
        )
        order: list = []
        dispatched: list = []
        marker_at: list = []

        async def fake_build_wait(branch, sha, **_kwargs):
            order.append(("build_wait", branch, sha))
            return "success", "build ended: success"

        async def fake_marker():
            # Position in `order` when the marker is recorded: after the
            # build wait, before the dispatch entry exists.
            marker_at.append(len(order))
            return 40

        async def fake_dispatch(**kwargs):
            order.append(("dispatch", kwargs))
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/41"

        async def fake_event(_sid, kind, payload):
            order.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "latest_dev_deploy_run_id", fake_marker)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)

        await sessions.manager._settle(7, exit_code=0, error=None)

        # The dispatch receives the prebuilt image tag and nothing branch-derived:
        # the workflow runs on a fixed trusted ref, so the session's agent-editable
        # branch never reaches the dev host.
        assert dispatched == [{"image_tag": "pr-772"}]
        # The build wait is handed the pushed commit, not just the branch:
        # the branch is force-pushed across retries, and a completed run of
        # an earlier commit on it is a stale image, not this session's.
        assert ("build_wait", "agent/feature-work/session-7", "f" * 40) in order
        # The build wait happens first, then the pre-dispatch marker — the
        # marker must see the runs as they stood before this dispatch's own
        # run exists — and only then the dispatch; the dispatched event
        # records the tag the environment now serves.
        build_idx = order.index(("build_wait", "agent/feature-work/session-7", "f" * 40))
        dispatch_idx = next(i for i, item in enumerate(order) if item[0] == "dispatch")
        assert build_idx < marker_at[0] <= dispatch_idx
        deploy_events = [
            item[1] for item in order if item[0] == EventKind.DEPLOY and item[1].get("status") == "dispatched"
        ]
        assert deploy_events == [
            {
                "status": "dispatched",
                "environment": "logos-dev",
                "url": "https://github.com/ls1intum/edutelligence/actions/runs/41",
                "image_tag": "pr-772",
            }
        ]

    async def test_deploy_is_aborted_when_the_pr_build_fails(self, monkeypatch, tmp_path):
        # A build that failed (or never ran) means the session's code is not
        # in any image; dispatching would deploy the old revision, so the
        # deploy is recorded as failed and nothing is dispatched.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(
            tmp_path,
            pr_url="https://github.com/ls1intum/edutelligence/pull/772",
            pushed_sha="f" * 40,
        )
        dispatched: list = []
        events: list = []

        async def fake_build_wait(_branch, _sha, **_kwargs):
            return "failed", "build ended: failure"

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert dispatched == []
        failed = [p for k, p in events if k == EventKind.DEPLOY and p.get("status") == "failed"]
        assert len(failed) == 1
        assert "image builds did not succeed" in failed[0]["error"]

    async def test_deploy_is_refused_when_the_session_opened_no_pull_request(self, monkeypatch, tmp_path):
        # The API allows deploy_to_dev without open_pull_request. Without a
        # pull request no image of the branch exists — the build workflow
        # only runs for PRs — and the only tags the registry carries are
        # main's. The deploy must be refused with a visible reason, never
        # silently dispatched against the stale latest images.
        sessions = self._patch_base(monkeypatch, tmp_path)
        # No result file: the session opened no pull request.
        events: list = []
        dispatched: list = []
        build_waits: list = []

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_build_wait(branch, **_kwargs):
            build_waits.append(branch)
            return "success", "build ended: success"

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert dispatched == []
        assert build_waits == []
        failed = [p for k, p in events if k == EventKind.DEPLOY and p.get("status") == "failed"]
        assert len(failed) == 1
        assert "no pull request" in failed[0]["error"]

    async def test_deploy_is_refused_when_the_finalizer_recorded_no_pushed_commit(self, monkeypatch, tmp_path):
        # The pull request exists but the finalizer recorded no commit the
        # branch was pushed to. Without that sha the build could not be
        # pinned to a revision — the branch may carry an earlier,
        # already-built commit, and settling the wait on a run of it would
        # deploy a stale image. Refuse instead of guessing.
        sessions = self._patch_base(monkeypatch, tmp_path)
        self._write_result(tmp_path, pr_url="https://github.com/ls1intum/edutelligence/pull/772")
        events: list = []
        dispatched: list = []
        build_waits: list = []

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_dispatch(**kwargs):
            dispatched.append(kwargs)
            return "https://github.com/ls1intum/edutelligence/actions/runs/1"

        async def fake_build_wait(branch, sha, **_kwargs):
            build_waits.append((branch, sha))
            return "success", "build ended: success"

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", self._async_value(self.SESSION_ROW))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)
        monkeypatch.setattr(sessions.github, "dispatch_dev_deploy", fake_dispatch)
        monkeypatch.setattr(sessions.github, "wait_for_pr_builds", fake_build_wait)

        await sessions.manager._settle(7, exit_code=0, error=None)

        assert dispatched == []
        assert build_waits == []
        failed = [p for k, p in events if k == EventKind.DEPLOY and p.get("status") == "failed"]
        assert len(failed) == 1
        assert "no pushed commit" in failed[0]["error"]


class TestRestartReconciliation:
    """Re-attaching to containers that outran the database after a restart.

    The runner can restart after a container is created and started but
    before the RUNNING transition stores its id. Such a row must be
    re-adopted — container id and derived branch persisted into the row —
    and moved only through valid state transitions, so a cancel that landed
    in the restart window is never overwritten and the credential-bearing
    container is never left unmanaged.
    """

    STARTING_ROW = {
        "id": 7,
        "workspace_name": "feature-work",
        "container_id": None,
        "branch_name": None,
    }
    CONTAINER = {
        "Id": "cid-x",
        "Labels": {"logos.agent.session": "7", "logos.agent.managed": "true"},
        "State": "running",
    }
    # What re-adoption must persist, and only as part of a successful
    # transition.
    META = {"container_id": "cid-x", "branch_name": branch_for(7, "feature-work")}

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    def _patch_base(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        return sessions

    def _patch_rows(self, monkeypatch, sessions, rows_by_status):
        async def fake_in_status(status):
            return rows_by_status.get(status, [])

        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)

    async def test_running_container_is_readopted_into_a_starting_row(self, monkeypatch, tmp_path):
        # The row still says 'starting' and knows no container id: the runner
        # restarted between the container start and the RUNNING transition.
        # Reconciliation must persist the id and the derived branch, move the
        # row to running, and hand the container to a supervisor.
        sessions = self._patch_base(monkeypatch, tmp_path)
        updated: list = []
        transitions: list = []
        supervised: list = []
        removed: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            return True

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([self.CONTAINER]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        # The id and branch ride on the transition that claims running — not
        # on a separate write — so the row can never carry them without also
        # being the owner of the container, and never on a terminal row.
        assert transitions == [(SessionStatus.RUNNING, self.META)]
        assert updated == []
        assert supervised == [(7, "cid-x")]
        # The matched container is not an orphan: it is supervised, not removed.
        assert removed == []

    async def test_a_recovered_row_is_not_requeried_after_its_own_transition(self, monkeypatch, tmp_path):
        # The status queries see the committed state, like the real database:
        # a STARTING row this reconciliation moves to RUNNING is in the
        # RUNNING result set by the time that status is queried. The
        # occupying rows must be snapshotted before any of the transitions
        # are committed — otherwise the recovered session's container is
        # already out of the live list when the second query returns the row,
        # and the active, supervised session is settled as vanished.
        sessions = self._patch_base(monkeypatch, tmp_path)
        states = {7: "starting"}
        transitions: list = []
        supervised: list = []
        settled: list = []

        async def fake_in_status(status):
            # A fresh read on every call, like the database: whatever has
            # been committed by now.
            return [self.STARTING_ROW] if states[7] == status.value else []

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            # A validated transition, like the database: only legal edges,
            # and the row really moves, so a later query sees it there.
            if not can_transition(SessionStatus(states[sid]), target):
                return False
            states[sid] = target.value
            return True

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_settle(_self, sid, **kwargs):
            settled.append((sid, kwargs))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([self.CONTAINER]))
        monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.SessionManager, "_settle", fake_settle)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await sessions.manager._reconcile()

        # The recovered session is re-adopted and supervised — and not
        # settled again from the RUNNING query that, against the committed
        # state, also returns it with its container already popped.
        assert transitions == [(SessionStatus.RUNNING, self.META)]
        assert supervised == [(7, "cid-x")]
        assert settled == []
        assert states[7] == "running"

    async def test_exited_container_from_a_starting_row_settles_through_running(self, monkeypatch, tmp_path):
        # The container exited while the runner was down, but the row never
        # left 'starting' — a state with no direct edge to a terminal state.
        # Reconciliation must normalize it through running so settlement's
        # transition is valid, then settle it as succeeded and remove the
        # container by the id it just re-adopted.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "exited"}
        updated: list = []
        transitions: list = []
        events: list = []
        removed: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            return True

        async def fake_state(_cid):
            return "exited", 0

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(
            sessions.db,
            "get_session",
            # The row as it stands after the re-adoption above: the cleanup
            # below can only find the container because the id is in there,
            # and settlement sees the row where the re-adoption left it.
            self._async_value(
                {
                    **self.STARTING_ROW,
                    "status": "running",
                    "container_id": "cid-x",
                    "deploy_to_dev": False,
                    "screenshot_paths": [],
                }
            ),
        )
        monkeypatch.setattr(sessions.docker_engine, "container_state", fake_state)
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)
        # The recovered exit is a clean one, so settlement would run the
        # finalizer; this test is about the reconciliation transitions.
        monkeypatch.setattr(sessions.SessionManager, "_finalize", self._async_value(True))

        await sessions.manager._reconcile()

        assert updated == []
        # The id and branch ride on the normalizing transition; starting has
        # no edge to succeeded, so settlement claims finalizing and the
        # terminal transition is the last.
        assert transitions[0] == (SessionStatus.RUNNING, self.META)
        assert [target for target, _ in transitions] == [
            SessionStatus.RUNNING,
            SessionStatus.FINALIZING,
            SessionStatus.SUCCEEDED,
        ]
        assert removed == ["cid-x"]
        assert events == [(EventKind.STATUS, {"status": "succeeded", "exit_code": 0, "error": None})]

    async def test_a_finalizing_row_refinalizes_after_a_restart(self, monkeypatch, tmp_path):
        # The runner restarted while the finalizer ran: the row is
        # finalizing, the agent container is gone, and the helper container
        # was swept by the label check. The working copy is intact on the
        # volume, and the finalizer is idempotent, so the row settles
        # through a fresh finalizer run — a clean exit, not a "container
        # vanished" failure, which would fail sessions whose work had in
        # fact landed.
        sessions = self._patch_base(monkeypatch, tmp_path)
        finalizing_row = {
            **self.STARTING_ROW,
            "status": "finalizing",
            "branch_name": "agent/feature-work/session-7",
        }
        settled: list = []
        removed: list = []

        async def fake_settle(_self, sid, **kwargs):
            settled.append((sid, kwargs))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        # No live container at all: the agent's has exited, the helper's
        # was removed by the reconciliation's own sweep.
        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.FINALIZING: [finalizing_row]})
        monkeypatch.setattr(sessions.SessionManager, "_settle", fake_settle)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        # Settled as a clean exit — the finalizer will run again — never as
        # a vanished-container failure.
        assert settled == [(7, {"exit_code": 0, "error": None})]
        assert removed == []

    async def test_paused_container_from_a_starting_row_normalizes_through_running(self, monkeypatch, tmp_path):
        # The platform paused the container inside the start window, before
        # the row ever reached 'running'. starting -> paused is not an edge,
        # so the row takes the only path that is: a later resume still has a
        # valid edge to leave from.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "paused"}
        updated: list = []
        transitions: list = []
        supervised: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            return True

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await sessions.manager._reconcile()

        # The metadata rides on the normalizing transition; the second hop
        # to paused carries none.
        assert transitions == [(SessionStatus.RUNNING, self.META), (SessionStatus.PAUSED, {})]
        assert updated == []
        assert supervised == [(7, "cid-x")]

    async def test_created_container_from_a_starting_row_is_started_not_settled(self, monkeypatch, tmp_path):
        # The runner restarted between creating and starting the container.
        # Docker reports it 'created' with exit code 0 — settling that would
        # record a success for an agent that never ran. A 'starting' row
        # continues what the launch began: start the container and supervise
        # it.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "created"}
        updated: list = []
        transitions: list = []
        started: list = []
        supervised: list = []
        settled: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **fields):
            transitions.append((target, fields))
            return True

        async def fake_start(cid):
            started.append(cid)

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_settle(_self, sid, **kwargs):
            settled.append((sid, kwargs))

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.SessionManager, "_settle", fake_settle)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", noop)

        await sessions.manager._reconcile()

        # No settle: a created container has no exit, however green, and no
        # orphan removal: the container is put to work. The id and branch
        # ride on the transition that claims running.
        assert settled == []
        assert started == ["cid-x"]
        assert transitions == [(SessionStatus.RUNNING, self.META)]
        assert supervised == [(7, "cid-x")]
        assert updated == []

    async def test_created_container_with_an_occupying_row_is_failed_and_removed(self, monkeypatch, tmp_path):
        # The container id is only stored once the start succeeded, so a
        # running row with a created container is inconsistent: it is failed
        # with a visible reason and removed, never trusted to run the
        # session.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "created"}
        running_row = {
            **self.STARTING_ROW,
            "container_id": "cid-x",
            "branch_name": "agent/feature-work/session-7",
        }
        transitions: list = []
        started: list = []
        removed: list = []
        events: list = []

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return True

        async def fake_start(cid):
            started.append(cid)

        async def fake_event(_sid, kind, payload):
            events.append((kind, payload))

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        async def noop(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.RUNNING: [running_row]})
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(
            sessions.db,
            "get_session",
            self._async_value({**running_row, "deploy_to_dev": False, "screenshot_paths": []}),
        )
        monkeypatch.setattr(sessions.db, "add_event", fake_event)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        assert started == []
        # Settled with an error: straight to FAILED from running, no
        # normalization through states the session never had.
        assert transitions == [SessionStatus.FAILED]
        assert removed == ["cid-x"]
        failed = [p for k, p in events if k == EventKind.STATUS]
        assert len(failed) == 1
        assert "never started" in failed[0]["error"]

    async def test_cancel_winning_re_adoption_stops_and_removes_the_container(self, monkeypatch, tmp_path):
        # A cancel that lands in the restart window moves the 'starting'
        # row to 'cancelled' before re-adoption's transition can claim it —
        # and, seeing no container id in the row yet, it stops nothing. The
        # transition must lose, and reconciliation must give the container
        # back by the id Docker told it about: no supervision, and no id
        # written into the now-terminal row.
        sessions = self._patch_base(monkeypatch, tmp_path)
        updated: list = []
        transitions: list = []
        supervised: list = []
        stopped: list = []
        removed: list = []

        async def fake_update(sid, **fields):
            updated.append((sid, fields))

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            # The cancel claimed the row first: every reconciliation
            # transition loses.
            return False

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([self.CONTAINER]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "update_session", fake_update)
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        # One transition attempt, lost to the cancel — and the
        # credential-bearing container is given back: stopped and removed,
        # never supervised, and the row is left untouched.
        assert transitions == [SessionStatus.RUNNING]
        assert stopped == ["cid-x"]
        assert removed == ["cid-x"]
        assert supervised == []
        assert updated == []

    async def test_cancel_winning_re_adoption_of_a_started_created_container_stops_it(self, monkeypatch, tmp_path):
        # The same race on the created path: the container is started, then
        # the transition to running loses to a cancel that landed in the
        # restart window. The just-started, credential-bearing agent must be
        # stopped and removed, not supervised.
        sessions = self._patch_base(monkeypatch, tmp_path)
        container = {**self.CONTAINER, "State": "created"}
        transitions: list = []
        started: list = []
        supervised: list = []
        stopped: list = []
        removed: list = []

        async def fake_transition(sid, target, **_fields):
            transitions.append(target)
            return False

        async def fake_start(cid):
            started.append(cid)

        def fake_supervise(_self, sid, cid):
            supervised.append((sid, cid))

        async def fake_stop(cid, **_kwargs):
            stopped.append(cid)

        async def fake_remove(cid, **_kwargs):
            removed.append(cid)

        monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", self._async_value([container]))
        self._patch_rows(monkeypatch, sessions, {SessionStatus.STARTING: [self.STARTING_ROW]})
        monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
        monkeypatch.setattr(sessions.docker_engine, "start_container", fake_start)
        monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
        monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

        await sessions.manager._reconcile()

        # Lost the race after the start: the agent is stopped and removed.
        assert started == ["cid-x"]
        assert transitions == [SessionStatus.RUNNING]
        assert stopped == ["cid-x"]
        assert removed == ["cid-x"]
        assert supervised == []


class TestReplyDelivery:
    """An answer that GitHub refused once is not an answer lost.

    Delivery happens when a session settles, and its trigger counts as
    handled from then on — so without a retry a single timeout would leave
    somebody waiting on a thread forever.
    """

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_a_failed_delivery_is_recorded_as_pending(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        (tmp_path / "7").mkdir()
        (tmp_path / "7" / "reply.md").write_text("the answer")
        attempts: list = []

        async def failing_reply(_target, _body):
            raise RuntimeError("502 from GitHub")

        async def record(session_id, *, delivered):
            attempts.append((session_id, delivered))

        monkeypatch.setattr(sessions.db, "get_session", self._async_value({"reply_target": "issue:772"}))
        monkeypatch.setattr(sessions.db, "record_reply_attempt", record)
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))
        monkeypatch.setattr(sessions.SessionManager, "_send_reply", staticmethod(failing_reply))

        await sessions.SessionManager()._post_reply(7)

        assert attempts == [(7, False)]

    async def test_a_pending_answer_is_tried_again(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        (tmp_path / "7").mkdir()
        (tmp_path / "7" / "reply.md").write_text("the answer")
        posted: list = []
        attempts: list = []

        async def owing(_max_attempts):
            return [{"id": 7, "reply_target": "issue:772", "reply_attempts": 1}]

        async def send(target, body):
            posted.append((target, body))
            return "https://github.com/x/y#c9"

        async def record(session_id, *, delivered):
            attempts.append((session_id, delivered))

        monkeypatch.setattr(sessions.db, "sessions_owing_a_reply", owing)
        monkeypatch.setattr(sessions.db, "get_session", self._async_value({"reply_target": "issue:772"}))
        monkeypatch.setattr(sessions.db, "record_reply_attempt", record)
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))
        monkeypatch.setattr(sessions.SessionManager, "_send_reply", staticmethod(send))

        await sessions.SessionManager().deliver_pending_replies()

        assert posted == [("issue:772", "the answer")]
        assert attempts == [(7, True)]

    async def test_a_delivered_answer_is_not_posted_twice(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        (tmp_path / "7").mkdir()
        (tmp_path / "7" / "reply.md").write_text("the answer")
        posted: list = []

        async def send(target, body):
            posted.append(target)
            return "url"

        monkeypatch.setattr(
            sessions.db,
            "get_session",
            self._async_value({"reply_target": "issue:772", "reply_posted_at": "2026-09-02T18:00:00Z"}),
        )
        monkeypatch.setattr(sessions.db, "record_reply_attempt", self._async_value(None))
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))
        monkeypatch.setattr(sessions.SessionManager, "_send_reply", staticmethod(send))

        await sessions.SessionManager()._post_reply(7)

        assert posted == []

    async def test_an_oversized_answer_is_shortened_rather_than_refused(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        (tmp_path / "7").mkdir()
        (tmp_path / "7" / "reply.md").write_text("x" * 80_000)
        posted: list = []

        async def send(_target, body):
            posted.append(body)
            return "url"

        monkeypatch.setattr(sessions.db, "get_session", self._async_value({"reply_target": "issue:772"}))
        monkeypatch.setattr(sessions.db, "record_reply_attempt", self._async_value(None))
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))
        monkeypatch.setattr(sessions.SessionManager, "_send_reply", staticmethod(send))

        await sessions.SessionManager()._post_reply(7)

        # GitHub rejects a body over 65 536 characters outright, and a
        # rejected answer is no answer.
        assert len(posted[0]) < 65_000
        assert posted[0].endswith("_[answer truncated]_")


class TestOperatorControls:
    """The kill switch, from the scheduler's side."""

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_pausing_hands_back_what_the_runner_holds(self, monkeypatch, tmp_path):
        from app import capacity, controls, sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        paused: list = []
        claimed: list = []

        async def stopped():
            return {"mode": "paused", "mode_reason": "incident", "max_parallel": None, "updated_by": "tobias"}

        async def fake_pause(cid, **_kwargs):
            paused.append(cid)
            return True

        async def fake_claim(_limit, *, include_triggered: bool = True):
            claimed.append(1)
            return []

        monkeypatch.setattr(controls.db, "get_controls", stopped)
        controls.forget()
        monkeypatch.setattr(
            sessions.capacity,
            "read_load",
            self._async_value(capacity.Reading(load=0.0, busy_slots=0, total_slots=4, queue_total=0, ok=True)),
        )
        monkeypatch.setattr(sessions.db, "sessions_in_status", self._async_value([{"id": 7, "container_id": "cid-7"}]))
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "claim_session", _claim_one(fake_claim))
        monkeypatch.setattr(sessions.db, "next_queued_session", _peek)
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))
        monkeypatch.setattr(sessions.docker_engine, "pause_container", fake_pause)
        monkeypatch.setattr(sessions.docker_engine, "disconnect_network", self._async_value(True))

        await sessions.SessionManager().scheduler_pass()

        # Running work is handed back, and nothing is admitted — but nothing
        # is cancelled either, so releasing the switch resumes it.
        assert paused == ["cid-7"]
        assert claimed == []

    async def test_draining_stops_admission_without_pausing_anything(self, monkeypatch, tmp_path):
        from app import capacity, controls, sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        claimed: list = []

        async def drained():
            return {"mode": "draining", "mode_reason": "before a deploy", "max_parallel": None, "updated_by": "t"}

        async def fake_claim(_limit, *, include_triggered: bool = True):
            claimed.append(1)
            return []

        monkeypatch.setattr(controls.db, "get_controls", drained)
        controls.forget()
        monkeypatch.setattr(
            sessions.capacity,
            "read_load",
            self._async_value(capacity.Reading(load=0.0, busy_slots=0, total_slots=4, queue_total=0, ok=True)),
        )
        paused: list = []

        async def fake_pause(cid, **_kwargs):
            paused.append(cid)
            return True

        monkeypatch.setattr(sessions.db, "sessions_in_status", self._async_value([{"id": 7, "container_id": "cid-7"}]))
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", fake_claim)
        monkeypatch.setattr(sessions.db, "claim_session", _claim_one(fake_claim))
        monkeypatch.setattr(sessions.db, "next_queued_session", _peek)
        monkeypatch.setattr(sessions.docker_engine, "pause_container", fake_pause)
        monkeypatch.setattr(sessions.docker_engine, "disconnect_network", self._async_value(True))
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))

        await sessions.SessionManager().scheduler_pass()

        # Nothing new is admitted, and the session already running is left
        # alone — that is what separates draining from pausing.
        assert claimed == []
        assert paused == []


class TestWorkspaceHousekeeping:
    """Workspaces the runner made for itself do not accumulate."""

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_a_finished_workspace_gives_back_its_volume_and_keeps_its_history(self, monkeypatch):
        from app import sessions

        removed_volumes: list = []
        archived: list = []
        deleted: list = []

        async def disposable(_cutoff):
            return [{"id": 3, "name": "issue-812-oom", "volume_name": "logos_agent_ws_issue-812-oom"}]

        async def archive(workspace_id):
            archived.append(workspace_id)
            return True

        async def delete(workspace_id):
            deleted.append(workspace_id)
            return True

        async def remove_volume(name, **_kwargs):
            removed_volumes.append(name)

        monkeypatch.setattr(sessions.db, "disposable_workspaces", disposable)
        monkeypatch.setattr(sessions.db, "archive_workspace", archive)
        monkeypatch.setattr(sessions.db, "delete_workspace", delete)
        monkeypatch.setattr(sessions.docker_engine, "remove_volume", remove_volume)

        await sessions.SessionManager().sweep_workspaces()

        assert removed_volumes == ["logos_agent_ws_issue-812-oom"]
        assert archived == [3]
        # Deleting the row would cascade into every finished session in it:
        # the history, the trigger references that keep assignments from
        # being worked twice, and any answer still waiting to be delivered.
        assert deleted == []

    async def test_a_volume_that_could_not_be_removed_is_tried_again(self, monkeypatch):
        from app import sessions

        archived: list = []

        async def disposable(_cutoff):
            return [{"id": 3, "name": "issue-812", "volume_name": "vol"}]

        async def archive(workspace_id):
            archived.append(workspace_id)
            return True

        async def failing_remove(_name, **_kwargs):
            raise RuntimeError("volume is in use")

        monkeypatch.setattr(sessions.db, "disposable_workspaces", disposable)
        monkeypatch.setattr(sessions.db, "archive_workspace", archive)
        monkeypatch.setattr(sessions.docker_engine, "remove_volume", failing_remove)

        await sessions.SessionManager().sweep_workspaces()

        # Not archived, so the next sweep finds it and tries the volume
        # again — archiving first would leave a volume nothing tracks.
        assert archived == []

    async def test_a_workspace_that_just_took_work_is_left_alone(self, monkeypatch):
        from app import sessions

        async def disposable(_cutoff):
            return [{"id": 3, "name": "issue-812", "volume_name": "vol"}]

        async def refuses(_workspace_id):
            # A session was accepted into it between the query and here.
            return False

        async def remove_volume(_name, **_kwargs):
            return None

        monkeypatch.setattr(sessions.db, "disposable_workspaces", disposable)
        monkeypatch.setattr(sessions.db, "archive_workspace", refuses)
        monkeypatch.setattr(sessions.docker_engine, "remove_volume", remove_volume)

        # The archive refuses under the same row lock a session creation
        # takes, so nothing is lost by the volume already being gone: the
        # next preparation clones it again.
        await sessions.SessionManager().sweep_workspaces()


class TestMissingSessionImage:
    """A missing image is an artefact that is not there, not a runner bug."""

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_the_session_says_what_is_missing(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)
        settled: list = []
        created: list = []

        async def no_image(_image):
            return False

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "cid"

        async def fake_settle(_self, sid, *, exit_code, error):
            settled.append((sid, error))

        monkeypatch.setattr(sessions.docker_engine, "image_present", no_image)
        monkeypatch.setattr(sessions.docker_engine, "ensure_volume", self._async_value(None))
        monkeypatch.setattr(sessions.docker_engine, "volume_mountpoint", self._async_value("/vol"))
        monkeypatch.setattr(sessions.docker_engine, "create_session_container", fake_create)
        monkeypatch.setattr(
            sessions.db,
            "get_workspace",
            self._async_value({"id": 1, "name": "issue-812", "base_branch": "main", "volume_name": "vol"}),
        )
        monkeypatch.setattr(sessions.SessionManager, "_settle", fake_settle)

        await sessions.SessionManager()._launch(
            {"id": 7, "workspace_id": 1, "task": "a task", "model": None, "screenshot_paths": []}
        )

        assert created == []
        assert len(settled) == 1
        message = settled[0][1]
        assert "not available on this host" in message and "build of the default branch" in message


class TestResumeCeiling:
    """An operator's ceiling holds for resumed sessions too.

    Resuming is where it is easiest to overshoot: the check is naturally
    written once, before a loop that then resumes everything.
    """

    @staticmethod
    def _async_value(value):
        async def fake(*_args, **_kwargs):
            return value

        return fake

    async def test_only_as_many_are_resumed_as_the_ceiling_allows(self, monkeypatch, tmp_path):
        from app import capacity, controls, sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        resumed: list = []

        async def ceiling_of_two():
            return {"mode": "running", "mode_reason": "", "max_parallel": 2, "updated_by": "tobias"}

        async def in_status(status):
            if status is SessionStatus.PAUSED:
                return [{"id": i, "container_id": f"cid-{i}"} for i in (1, 2, 3, 4)]
            return []

        async def fake_unpause(cid, **_kwargs):
            resumed.append(cid)
            return True

        monkeypatch.setattr(controls.db, "get_controls", ceiling_of_two)
        controls.forget()
        monkeypatch.setattr(
            sessions.capacity,
            "read_load",
            self._async_value(capacity.Reading(load=0.0, busy_slots=0, total_slots=10, queue_total=0, ok=True)),
        )
        monkeypatch.setattr(sessions.db, "sessions_in_status", in_status)
        monkeypatch.setattr(sessions.db, "transition_session", self._async_value(True))
        monkeypatch.setattr(sessions.db, "add_event", self._async_value(None))
        monkeypatch.setattr(sessions.docker_engine, "connect_network", self._async_value(True))
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", fake_unpause)

        await sessions.SessionManager().scheduler_pass()

        # Four were paused and the platform is idle; the ceiling is what
        # stops the fourth, third and — here — everything past the second.
        assert resumed == ["cid-1", "cid-2"]


class TestAdmissionMeasuresTheRightLane:
    """A queued session on a saturated model must not enter on an idle one.

    The launch checks permission afterwards; it never rechecks capacity. So
    the reading admission decides against has to be of the lane the session
    it is about to claim would actually be served by.
    """

    async def test_the_lane_measured_is_the_candidate_s(self, monkeypatch):
        from app import capacity, model_policy, sessions

        policy = model_policy.ModelPolicy(
            local_models=frozenset({"model-a", "model-b"}),
            offered=("model-a", "model-b"),
            local_deployments=frozenset({("15", "1"), ("15", "2")}),
            deployments_by_model={
                "model-a": frozenset({("15", "1")}),
                "model-b": frozenset({("15", "2")}),
            },
            ok=True,
            unknown=False,
            detail="two local models",
        )
        lanes: list = []

        async def refresh():
            return policy

        async def read_load(timeout_s: float = 5.0, lane=None, ours=None):
            lanes.append(lane)
            return capacity.Reading(load=0.0, busy_slots=0, total_slots=20, queue_total=0, ok=True)

        async def peek(*, include_triggered: bool = True):
            return {"id": 7, "model": "model-b", "workspace_id": 1}

        async def claim(_limit, *, include_triggered: bool = True):
            return []

        async def claim_session(_session_id, *, trigger_quota=None):
            return None

        async def none(_status):
            return []

        monkeypatch.setattr(model_policy, "refresh", refresh)
        monkeypatch.setattr(model_policy, "_current", policy)
        monkeypatch.setattr(capacity, "read_load", read_load)
        monkeypatch.setattr(sessions.db, "next_queued_session", peek)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", claim)
        monkeypatch.setattr(sessions.db, "claim_session", claim_session)
        monkeypatch.setattr(sessions.db, "sessions_in_status", none)

        await sessions.manager.scheduler_pass()

        # The pass itself measures everything the key may use — that reading
        # decides whether to hand capacity back — and admission measures the
        # one model it is about to admit.
        assert lanes[0] == policy.local_deployments
        assert lanes[-1] == frozenset({("15", "2")})

    async def test_nothing_queued_means_nothing_measured_twice(self, monkeypatch):
        from app import capacity, sessions

        readings: list = []

        async def read_load(timeout_s: float = 5.0, lane=None, ours=None):
            readings.append(lane)
            return capacity.Reading(load=0.0, busy_slots=0, total_slots=20, queue_total=0, ok=True)

        async def none(_status):
            return []

        async def refuse(_limit, *, include_triggered: bool = True):
            raise AssertionError("nothing is queued; there is nothing to claim")

        monkeypatch.setattr(capacity, "read_load", read_load)
        monkeypatch.setattr(sessions.db, "sessions_in_status", none)
        monkeypatch.setattr(sessions.db, "claim_queued_sessions", refuse)

        await sessions.manager.scheduler_pass()

        # Two of the same moment — with and without this runner's share —
        # and nothing queued, so admission takes none of its own.
        assert len(readings) == 2


class TestPicturesTravelWithTheRequest:
    """An issue whose whole description is a screenshot.

    The sandbox has no network, so the agent met one of those with WebFetch,
    was refused, read code for an hour and changed nothing. The runner has
    the token and the egress; the agent can read a local image perfectly
    well, it just cannot go and get one.
    """

    @staticmethod
    def install(monkeypatch, tmp_path, answers):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        monkeypatch.setattr(sessions, "_give_to_session_user", lambda _path: None)
        asked: list = []

        async def fetch_image(url, *, max_bytes):
            asked.append(url)
            return answers.get(url)

        monkeypatch.setattr(sessions.github, "fetch_image", fetch_image)
        return asked

    async def test_an_image_in_the_request_is_downloaded(self, monkeypatch, tmp_path):
        from app import sessions

        url = "https://github.com/user-attachments/assets/69276878-e522"
        self.install(monkeypatch, tmp_path, {url: (b"\x89PNG...", "image/png")})

        paths = await sessions.manager._collect_attachments(30, f'<img width="239" src="{url}" />')

        assert paths == ["/artifacts/attachments/01.png"]
        assert (tmp_path / "30" / "attachments" / "01.png").read_bytes() == b"\x89PNG..."

    async def test_a_request_with_no_pictures_fetches_nothing(self, monkeypatch, tmp_path):
        from app import sessions

        asked = self.install(monkeypatch, tmp_path, {})

        assert await sessions.manager._collect_attachments(30, "Plain prose about a bug.") == []
        assert asked == []

    async def test_something_that_is_not_an_image_is_left(self, monkeypatch, tmp_path):
        from app import sessions

        url = "https://example.com/thing.png"
        self.install(monkeypatch, tmp_path, {url: (b"<html>", "text/html")})

        assert await sessions.manager._collect_attachments(30, f"![shot]({url})") == []

    async def test_a_fetch_that_fails_does_not_fail_the_session(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))

        async def broken(_url, *, max_bytes):
            raise RuntimeError("502")

        monkeypatch.setattr(sessions.github, "fetch_image", broken)

        # A picture that cannot be had is a picture the agent works without,
        # which is where it was before.
        assert await sessions.manager._collect_attachments(30, "![shot](https://example.com/a.png)") == []


def _claim_one(fake_claim):
    """The targeted claim, expressed through a test's own batch stub.

    Admission takes the row it measured rather than "the next one"; these
    tests care about *whether* something was claimed, so this keeps their
    existing fakes honest without each of them growing a second one.
    """

    async def claim_session(_session_id: int, *, trigger_quota=None):
        taken = await fake_claim(1)
        return taken[0] if taken else None

    return claim_session


async def _peek(*, include_triggered: bool = True):
    """What admission looks at before it measures: any queued session.

    The tests that stub the claim are about admission, not about which row
    it picks, so the peek answers with a plain one on the runner's own
    model.
    """
    return {"id": 7, "model": None, "workspace_id": 1}


class TestAFailedRequestComesBack:
    """A request the runner could not finish is one nobody is coming back to.

    The trigger reference counts as handled forever, so no later pass finds
    it again: three of them sat failed and permanently invisible until
    somebody read the database by hand.
    """

    @staticmethod
    def install(monkeypatch, row):
        from app import sessions

        taken_up: list = []

        async def get_session(_session_id):
            return row

        async def transition(_sid, _target, **_fields):
            return True

        async def add_event(*_args, **_kwargs):
            return None

        async def nothing(*_args, **_kwargs):
            return None

        async def take_up_again(_self, session, *, by="the runner", note=""):
            taken_up.append((session["id"], note))
            return 99

        monkeypatch.setattr(sessions.db, "get_session", get_session)
        monkeypatch.setattr(sessions.db, "transition_session", transition)
        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.SessionManager, "_cleanup_container", nothing)
        monkeypatch.setattr(sessions.SessionManager, "_post_reply", nothing)
        monkeypatch.setattr(sessions.SessionManager, "_react", nothing)
        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)
        return taken_up

    async def test_a_failed_triggered_session_is_taken_up_again(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        taken_up = self.install(
            monkeypatch,
            {
                "id": 52,
                "status": "running",
                "workspace_id": 1,
                "task": "answer the review",
                "trigger_ref": "pr-858-review-1",
                "error": None,
            },
        )

        await sessions.manager._settle(52, exit_code=1, error="the session ran past its budget")

        assert taken_up and taken_up[0][0] == 52
        assert "did not finish" in taken_up[0][1]

    async def test_a_session_a_person_started_is_theirs(self, monkeypatch, tmp_path):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        taken_up = self.install(
            monkeypatch,
            {"id": 52, "status": "running", "workspace_id": 1, "task": "t", "trigger_ref": None, "error": None},
        )

        await sessions.manager._settle(52, exit_code=1, error="something went wrong")

        assert taken_up == []


class TestTakingWorkUpAgain:
    """The same request, once more, without a person having to ask."""

    ROW = {
        "id": 30,
        "workspace_id": 3,
        "task": "answer the review on #858",
        "trigger_kind": "review",
        "trigger_ref": "pr-858-review-1",
        "branch_name": "logos/issue-797",
        "reply_target": "issue:858",
        "reaction_target": "/repos/x/y/issues/858",
        "priority": 80,
        "open_pull_request": False,
    }

    @staticmethod
    def install(monkeypatch, *, attempts: int):
        from app import sessions

        created: list = []

        async def attempts_for_trigger(_ref):
            return attempts

        async def create_session(**kwargs):
            created.append(kwargs)
            return 99

        async def add_event(*_args, **_kwargs):
            return None

        async def scheduler_pass(_self=None):
            return None

        monkeypatch.setattr(sessions.db, "attempts_for_trigger", attempts_for_trigger)
        monkeypatch.setattr(sessions.db, "create_session", create_session)
        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.SessionManager, "scheduler_pass", scheduler_pass)
        return created

    async def test_the_work_comes_back_where_it_came_from(self, monkeypatch):
        from app import sessions

        created = self.install(monkeypatch, attempts=1)

        assert await sessions.manager.take_up_again(dict(self.ROW)) == 99
        # The branch, the thread and the urgency belong to the request, not
        # to the attempt that failed.
        assert created[0]["branch"] == "logos/issue-797"
        assert created[0]["reply_target"] == "issue:858"
        assert created[0]["priority"] == 80
        assert created[0]["deploy_to_dev"] is False

    async def test_a_request_nothing_can_be_made_of_stops(self, monkeypatch):
        from app import sessions

        created = self.install(monkeypatch, attempts=sessions._MAX_ATTEMPTS_PER_REQUEST)

        assert await sessions.manager.take_up_again(dict(self.ROW)) is None
        assert created == []


class TestAPausedSessionThatCannotComeBack:
    """One stuck session must not stop the whole queue.

    Production: a paused session's container was removed underneath it, so
    every pass tried to reattach it, failed, and returned — because
    resuming comes before admitting. Two sessions sat queued behind it for
    as long as it existed, and the log filled with the same line every
    fifteen seconds.
    """

    @staticmethod
    def install(monkeypatch, *, exists: bool):
        from app import capacity, sessions

        settled: list = []
        resumed: list = []

        async def reading(timeout_s: float = 5.0, lane=None, ours=None):
            return capacity.Reading(load=0.0, busy_slots=0, total_slots=20, queue_total=0, ok=True)

        async def container_state(_container_id):
            return ("running" if exists else "gone"), None

        async def settle(_self, session_id, *, exit_code, error):
            settled.append((session_id, error))

        async def connect_network(_network, _container_id):
            resumed.append("attached")
            return True

        async def unpause(_container_id):
            return True

        async def transition(_sid, _target, **_fields):
            return True

        async def add_event(*_args, **_kwargs):
            return None

        monkeypatch.setattr(capacity, "read_load", reading)
        monkeypatch.setattr(sessions.docker_engine, "container_state", container_state)
        monkeypatch.setattr(sessions.docker_engine, "connect_network", connect_network)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", unpause)
        monkeypatch.setattr(sessions.db, "transition_session", transition)
        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.SessionManager, "_settle", settle)
        return settled, resumed

    async def test_a_vanished_container_settles_the_session(self, monkeypatch):
        from app import sessions

        settled, resumed = self.install(monkeypatch, exists=False)

        assert await sessions.manager._resume({"id": 34, "container_id": "cid-34"}, "load 0%") is False
        assert settled and settled[0][0] == 34
        assert "disappeared" in settled[0][1]
        # It was never attached to anything: there was nothing there.
        assert resumed == []

    async def test_a_session_that_is_still_there_resumes(self, monkeypatch):
        from app import sessions

        settled, resumed = self.install(monkeypatch, exists=True)

        assert await sessions.manager._resume({"id": 34, "container_id": "cid-34"}, "load 0%") is True
        assert settled == [] and resumed == ["attached"]

    async def test_the_queue_moves_on_when_nothing_could_be_resumed(self, monkeypatch):
        from app import capacity, sessions

        admitted: list = []

        async def reading(timeout_s: float = 5.0, lane=None, ours=None):
            return capacity.Reading(load=0.0, busy_slots=0, total_slots=20, queue_total=0, ok=True)

        async def in_status(status):
            if status is sessions.SessionStatus.PAUSED:
                return [{"id": 34, "container_id": "cid-34"}]
            return []

        async def no_resume(_self, _session, _reason):
            return False

        async def peek(*, include_triggered: bool = True):
            return {"id": 37, "model": None, "workspace_id": 1}

        async def claim_session(session_id, *, trigger_quota=None):
            admitted.append(session_id)
            return None

        monkeypatch.setattr(capacity, "read_load", reading)
        monkeypatch.setattr(sessions.db, "sessions_in_status", in_status)
        monkeypatch.setattr(sessions.db, "next_queued_session", peek)
        monkeypatch.setattr(sessions.db, "claim_session", claim_session)
        monkeypatch.setattr(sessions.SessionManager, "_resume", no_resume)

        await sessions.manager.scheduler_pass()

        # Nothing was resumed, so the pass has not spent its turn: the work
        # behind the stuck session gets its chance.
        assert admitted == [37]


class TestWhoseContainerIsIt:
    """Settlement may only clear up after a row that is finished.

    Production: a settlement raced the pauser, found the row in 'paused',
    declined to record anything — and removed the container anyway. The
    session was then unresumable, held its workspace, and blocked the queue
    behind it. Removing somebody else's container is the one thing a
    settlement that has decided not to own the row must not do.
    """

    @staticmethod
    def install(monkeypatch, tmp_path, status: str):
        from app import sessions

        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
        removed: list = []

        async def get_session(_session_id):
            return {"id": 34, "status": status, "container_id": "cid-34"}

        async def cleanup(_self, session_id):
            removed.append(session_id)

        monkeypatch.setattr(sessions.db, "get_session", get_session)
        monkeypatch.setattr(sessions.SessionManager, "_cleanup_container", cleanup)
        return removed

    async def test_a_paused_row_keeps_its_container(self, monkeypatch, tmp_path):
        from app import sessions

        removed = self.install(monkeypatch, tmp_path, "paused")

        await sessions.manager._settle(34, exit_code=0, error=None)

        assert removed == []

    async def test_a_cancelled_row_gives_its_container_back(self, monkeypatch, tmp_path):
        from app import sessions

        removed = self.install(monkeypatch, tmp_path, "cancelled")

        await sessions.manager._settle(34, exit_code=0, error=None)

        # Finished for good: the container is a leftover.
        assert removed == [34]

    async def test_a_resume_that_throws_does_not_take_the_pass_with_it(self, monkeypatch):
        from app import sessions

        async def exists(_container_id):
            return "running", None

        async def attach(_network, _container_id):
            return True

        async def explodes(_container_id):
            raise sessions.docker_engine.DockerError(500, "something nobody expected")

        monkeypatch.setattr(sessions.docker_engine, "container_state", exists)
        monkeypatch.setattr(sessions.docker_engine, "connect_network", attach)
        monkeypatch.setattr(sessions.docker_engine, "unpause_container", explodes)

        # Everything behind this session — resuming the rest, admitting,
        # sweeping — would otherwise stop with it.
        assert await sessions.manager._resume({"id": 34, "container_id": "cid-34"}, "load 0%") is False


class TestASessionThatRanOutOfTime:
    """A session stopped by its own budget has a reason, and it is not "failed".

    Production ended one at exactly that: `failed`, exit code -1, and an
    empty error column — so the page, the thread and anybody reading the
    row learned nothing about why. The event log had it; the row is what
    everything else reads.
    """

    async def test_the_row_says_it_ran_out_of_time(self, monkeypatch):
        from app import sessions

        # A limit somebody configured — zero now means "no limit at all",
        # which is the default and the case below.
        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, session_timeout_s=1))
        settled: list = []

        async def state(_container_id):
            return "running", None

        async def stop(_container_id, **_kwargs):
            return None

        async def add_event(*_args, **_kwargs):
            return None

        async def settle(_self, session_id, *, exit_code, error):
            settled.append((session_id, exit_code, error))

        monkeypatch.setattr(sessions.docker_engine, "container_state", state)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", stop)
        monkeypatch.setattr(sessions.db, "add_event", add_event)
        monkeypatch.setattr(sessions.SessionManager, "_settle", settle)
        monkeypatch.setattr(sessions.SessionManager, "_collect_logs", lambda *_a, **_k: asyncio.sleep(0))

        await sessions.manager._supervise_session(7, "cid-7")

        assert len(settled) == 1
        session_id, exit_code, error = settled[0]
        assert session_id == 7 and exit_code == -1
        assert "ran past its" in error and "budget" in error


class TestNoClockUnlessSomebodyAsksForOne:
    """A session is bounded by capacity, not by a clock.

    A session that has read the repository for two hours and is halfway
    through a change is not stuck, and stopping it throws away everything it
    has done — uncommitted, in a checkout the next session resets. One did:
    an hour and a half of work, thirty-eight million tokens, killed at the
    deadline with nothing to show.
    """

    async def test_a_session_runs_until_it_is_done(self, monkeypatch):
        from app import sessions

        # The default: no limit configured.
        monkeypatch.setattr(sessions, "settings", replace(sessions.settings, session_timeout_s=0))
        stopped: list = []
        states = iter([("running", None), ("running", None), ("exited", 0)])

        async def state(_container_id):
            return next(states)

        async def stop(container_id, **_kwargs):
            stopped.append(container_id)

        async def settle(_self, session_id, *, exit_code, error):
            stopped.append(("settled", exit_code, error))

        async def nothing(*_args, **_kwargs):
            return None

        monkeypatch.setattr(sessions.docker_engine, "container_state", state)
        monkeypatch.setattr(sessions.docker_engine, "stop_container", stop)
        monkeypatch.setattr(sessions.db, "add_event", nothing)
        monkeypatch.setattr(sessions.SessionManager, "_settle", settle)
        monkeypatch.setattr(sessions.SessionManager, "_collect_logs", lambda *_a, **_k: asyncio.sleep(0))
        real_sleep = asyncio.sleep
        monkeypatch.setattr(sessions.asyncio, "sleep", lambda *_a, **_k: real_sleep(0))

        await sessions.manager._supervise_session(7, "cid-7")

        # It ended because the agent ended it, with its own exit code —
        # nothing was stopped on a clock.
        assert stopped == [("settled", 0, None)]


class TestFollowingTheChecks:
    """What happens to a pushed commit after the session that pushed it ends.

    A session settles minutes before CI concludes, so this is the only way
    it ever learns that its change was red. Three answers have to stay
    distinct: green (nothing owed), red (take the work up again), and not
    known yet (ask again — never a retry, and never a comment about a pull
    request that is fine).
    """

    ROW = {
        "id": 12,
        "workspace_id": 3,
        "task": "Fix the alignment.",
        "model": "qwen",
        "branch_name": "logos/agent/issue-797",
        "checks_sha": "d" * 40,
        "trigger_kind": "issue",
        "trigger_ref": "issue-797",
        "reply_target": "issue:797",
        "reaction_target": "/repos/x/y/issues/797",
        "priority": 50,
        "priority_reason": None,
        "open_pull_request": True,
        "finished_at": None,
    }

    @staticmethod
    def install(monkeypatch, *, checks, attempts=0):
        from app import sessions

        taken: list = []
        updates: list = []

        async def wait_for_checks(_sha, **_kwargs):
            return checks

        async def take_up_again(_self, session, *, by="the runner", note=""):
            taken.append(note)
            return 77

        async def update_session(session_id, **fields):
            updates.append((session_id, fields))

        async def attempts_for_trigger(_ref):
            return attempts

        monkeypatch.setattr(sessions.github, "wait_for_checks", wait_for_checks)
        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)
        monkeypatch.setattr(sessions.db, "update_session", update_session)
        monkeypatch.setattr(sessions.db, "attempts_for_trigger", attempts_for_trigger)
        return taken, updates

    async def test_a_red_build_comes_back_as_another_attempt(self, monkeypatch):
        from app import sessions

        taken, updates = self.install(monkeypatch, checks=("failed", "Logos Lint (failure)"))

        await sessions.manager._take_up_a_red_build(dict(self.ROW), "logos/agent/issue-797", "d" * 40)

        assert taken and "Logos Lint" in taken[0]
        assert (12, {"checks_watch": "done"}) in updates

    async def test_checks_that_have_not_concluded_are_not_a_failure(self, monkeypatch):
        from app import sessions

        taken, updates = self.install(monkeypatch, checks=("timeout", "still running"))

        await sessions.manager._take_up_a_red_build(dict(self.ROW), "logos/agent/issue-797", "d" * 40)

        # Nothing to fix, so nothing is queued — and the follow-up stays
        # owed, because "not known yet" is not an answer.
        assert taken == []
        assert updates == []

    async def test_green_checks_settle_the_follow_up(self, monkeypatch):
        from app import sessions

        taken, updates = self.install(monkeypatch, checks=("success", "all 4 check(s) passed"))

        await sessions.manager._take_up_a_red_build(dict(self.ROW), "logos/agent/issue-797", "d" * 40)

        assert taken == []
        assert (12, {"checks_watch": "done"}) in updates

    async def test_a_request_out_of_attempts_stops_being_watched(self, monkeypatch):
        from app import sessions

        taken, updates = self.install(
            monkeypatch,
            checks=("failed", "red"),
            attempts=sessions._MAX_ATTEMPTS_PER_REQUEST,
        )

        async def take_up_again(_self, session, *, by="the runner", note=""):
            taken.append(note)
            return None  # bounded: this request has had its three goes

        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)

        await sessions.manager._take_up_a_red_build(dict(self.ROW), "logos/agent/issue-797", "d" * 40)

        assert (12, {"checks_watch": "done"}) in updates

    async def test_a_follow_up_that_could_not_be_queued_stays_owed(self, monkeypatch):
        from app import sessions

        taken, updates = self.install(monkeypatch, checks=("failed", "red"), attempts=0)

        async def take_up_again(_self, session, *, by="the runner", note=""):
            return None  # the database blinked

        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)

        await sessions.manager._take_up_a_red_build(dict(self.ROW), "logos/agent/issue-797", "d" * 40)

        # Still pending: a transient failure must leave a way back, which
        # is the whole reason the intent is on the row.
        assert updates == []

    async def test_the_intent_is_written_down_before_anybody_watches(self, monkeypatch):
        from app import sessions

        _, updates = self.install(monkeypatch, checks=("timeout", "waiting"))
        started: list = []
        monkeypatch.setattr(
            sessions.SessionManager,
            "_start_watching",
            lambda _self, session, branch, sha: started.append((branch, sha)),
        )

        await sessions.manager._watch_the_checks(dict(self.ROW), "e" * 40)

        assert (12, {"checks_sha": "e" * 40, "checks_watch": "pending"}) in updates
        assert started == [("logos/agent/issue-797", "e" * 40)]

    async def test_a_session_a_person_queued_is_that_person_s_to_follow(self, monkeypatch):
        from app import sessions

        _, updates = self.install(monkeypatch, checks=("failed", "red"))
        row = {**self.ROW, "trigger_ref": None}

        await sessions.manager._watch_the_checks(row, "e" * 40)

        assert updates == []


class TestTakingUpAWatchAgain:
    """The follow-up outlives the process that started it.

    A redeploy in the couple of minutes between pushing and CI concluding
    used to lose it silently: the watcher was a background task and nothing
    else, and the red build waited for a person to notice.
    """

    ROW = {
        "id": 21,
        "workspace_id": 3,
        "task": "Fix it.",
        "branch_name": "logos/agent/issue-800",
        "checks_sha": "f" * 40,
        "trigger_ref": "issue-800",
        "finished_at": None,
    }

    @staticmethod
    def install(monkeypatch, rows):
        from app import sessions

        started: list = []
        updates: list = []

        async def sessions_awaiting_checks():
            return [dict(row) for row in rows]

        async def update_session(session_id, **fields):
            updates.append((session_id, fields))

        monkeypatch.setattr(sessions.db, "sessions_awaiting_checks", sessions_awaiting_checks)
        monkeypatch.setattr(sessions.db, "update_session", update_session)
        monkeypatch.setattr(
            sessions.SessionManager,
            "_start_watching",
            lambda _self, session, branch, sha: started.append((session["id"], branch, sha)),
        )
        return started, updates

    async def test_a_pending_row_is_picked_up(self, monkeypatch):
        from app import sessions

        started, _ = self.install(monkeypatch, [self.ROW])

        await sessions.manager.resume_check_watches()

        assert started == [(21, "logos/agent/issue-800", "f" * 40)]

    async def test_a_row_with_nothing_to_watch_is_closed(self, monkeypatch):
        from app import sessions

        started, updates = self.install(monkeypatch, [{**self.ROW, "checks_sha": None}])

        await sessions.manager.resume_check_watches()

        assert started == []
        assert updates == [(21, {"checks_watch": "done"})]

    async def test_checks_that_never_concluded_stop_being_asked_about(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        from app import sessions

        old = datetime.now(timezone.utc) - timedelta(seconds=sessions.CHECK_WATCH_HORIZON_S + 60)
        started, updates = self.install(monkeypatch, [{**self.ROW, "finished_at": old}])

        await sessions.manager.resume_check_watches()

        # Otherwise every scheduler pass forever asks GitHub about a pull
        # request whose checks were never queued.
        assert started == []
        assert updates == [(21, {"checks_watch": "done"})]

    async def test_a_database_that_will_not_answer_costs_nothing(self, monkeypatch):
        from app import sessions

        async def sessions_awaiting_checks():
            raise RuntimeError("no database")

        monkeypatch.setattr(sessions.db, "sessions_awaiting_checks", sessions_awaiting_checks)

        await sessions.manager.resume_check_watches()  # the pass goes on

    async def test_one_session_is_not_polled_twice_at_once(self, monkeypatch):
        from app import sessions

        polls: list = []

        async def wait_for_checks(_sha, **_kwargs):
            polls.append(_sha)
            await asyncio.sleep(0.05)
            return "timeout", "still running"

        async def update_session(session_id, **fields):
            return None

        monkeypatch.setattr(sessions.github, "wait_for_checks", wait_for_checks)
        monkeypatch.setattr(sessions.db, "update_session", update_session)

        sessions.manager._start_watching(dict(self.ROW), "logos/agent/issue-800", "f" * 40)
        sessions.manager._start_watching(dict(self.ROW), "logos/agent/issue-800", "f" * 40)
        await asyncio.sleep(0.1)

        assert len(polls) == 1


class TestARequestThatLostItsReplacement:
    """A failed session queues the next attempt itself — until it cannot.

    When that one call fails, the request is gone for good: its reference
    counts as handled forever, so no poll finds it again, and its reply has
    been abandoned. Nobody is coming back to it. So the rows are asked
    instead of a flag: a failure that is the newest attempt at a request
    with attempts left is a request owing a replacement, whether the
    settlement wrote anything down or not.
    """

    ROW = {
        "id": 31,
        "workspace_id": 3,
        "task": "Fix the alignment.",
        "model": None,
        "branch_name": "logos/agent/issue-800",
        "trigger_kind": "issue",
        "trigger_ref": "issue-800",
        "reply_target": "issue:800",
        "reaction_target": "/repos/x/y/issues/800",
        "priority": 50,
        "priority_reason": None,
        "open_pull_request": True,
        "error": "the container disappeared",
        "finished_at": None,
    }

    @staticmethod
    def install(monkeypatch, rows):
        from app import sessions

        asked: list = []
        taken: list = []

        async def sessions_owing_a_replacement(*, max_attempts, since):
            asked.append((max_attempts, since))
            return [dict(row) for row in rows]

        async def take_up_again(_self, session, *, by="the runner", note=""):
            taken.append((session["id"], note))
            return 99

        monkeypatch.setattr(sessions.db, "sessions_owing_a_replacement", sessions_owing_a_replacement)
        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)
        return asked, taken

    async def test_a_failure_nobody_replaced_is_taken_up(self, monkeypatch):
        from app import sessions

        _, taken = self.install(monkeypatch, [self.ROW])

        await sessions.manager.resume_retries()

        assert taken and taken[0][0] == 31
        # The replacement is told what happened to the attempt before it,
        # in the same words the settlement would have used.
        assert "the container disappeared" in taken[0][1]

    async def test_the_attempt_limit_is_carried_into_the_question(self, monkeypatch):
        from app import sessions

        asked, _ = self.install(monkeypatch, [])

        await sessions.manager.resume_retries()

        # Asked of the database rather than filtered afterwards: a request
        # at its limit must not come back every fifteen seconds to be
        # refused again.
        assert asked[0][0] == sessions._MAX_ATTEMPTS_PER_REQUEST

    async def test_nothing_owed_is_the_ordinary_case(self, monkeypatch):
        from app import sessions

        _, taken = self.install(monkeypatch, [])

        await sessions.manager.resume_retries()

        assert taken == []

    async def test_a_database_that_will_not_answer_costs_nothing(self, monkeypatch):
        from app import sessions

        async def broken(*, max_attempts, since):
            raise RuntimeError("no database")

        monkeypatch.setattr(sessions.db, "sessions_owing_a_replacement", broken)

        await sessions.manager.resume_retries()  # the pass goes on

    async def test_a_settlement_whose_retry_failed_is_picked_up_next_pass(self, monkeypatch):
        from app import sessions

        # The case the whole thing exists for: the settlement asked, the
        # database blinked, and the row is all that is left of the request.
        attempts: list = []

        async def take_up_again(_self, session, *, by="the runner", note=""):
            attempts.append(session["id"])
            return None if len(attempts) == 1 else 99

        async def sessions_owing_a_replacement(*, max_attempts, since):
            return [dict(self.ROW)] if len(attempts) < 2 else []

        monkeypatch.setattr(sessions.db, "sessions_owing_a_replacement", sessions_owing_a_replacement)
        monkeypatch.setattr(sessions.SessionManager, "take_up_again", take_up_again)

        await sessions.manager.resume_retries()
        await sessions.manager.resume_retries()

        assert attempts == [31, 31]
