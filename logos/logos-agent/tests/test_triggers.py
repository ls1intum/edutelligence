"""Tests for the sessions the runner queues by itself.

The interesting property is not that a poll queues something — it is that a
second poll over the same repository state queues nothing, that an approval
is not mistaken for work, and that the automation cannot fill the platform.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from app import triggers


def issue(number: int, title: str = "Something is wrong", body: str = "Details.") -> dict:
    return {"number": number, "title": title, "body": body}


def review(review_id: int, state: str = "CHANGES_REQUESTED", body: str = "Please fix X.") -> dict:
    return {
        "id": review_id,
        "state": state,
        "body": body,
        "user": {"login": "wasnertobias"},
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


class FakeRepo:
    """The GitHub reads a pass makes, with recorded results."""

    def __init__(self, issues=None, pulls=None, reviews=None, heads=None, comments=None):
        self.issues = issues or []
        self.pulls = pulls or []
        self.reviews = reviews or {}
        # Per pull request: (head ref, head repository). Defaults to an agent
        # branch in this repository, which is the case the runner acts on.
        self.heads = heads or {}
        self.comments = comments or {}
        self.review_calls = 0

    def install(self, monkeypatch):
        async def labelled_issues(_label, *, since):
            return self.issues

        async def labelled_pull_requests(_label):
            return self.pulls

        async def reviews_since(number, _since):
            self.review_calls += 1
            return self.reviews.get(number, [])

        async def pull_request(number):
            ref, repo = self.heads.get(number, (f"agent/pr/session-{number}", "ls1intum/edutelligence"))
            return {"number": number, "head": {"ref": ref, "repo": {"full_name": repo}}}

        async def review_comments(number, review_id):
            return self.comments.get((number, review_id), [])

        monkeypatch.setattr(triggers.github, "labelled_issues", labelled_issues)
        monkeypatch.setattr(triggers.github, "labelled_pull_requests", labelled_pull_requests)
        monkeypatch.setattr(triggers.github, "reviews_since", reviews_since)
        monkeypatch.setattr(triggers.github, "pull_request", pull_request)
        monkeypatch.setattr(triggers.github, "review_comments", review_comments)


class FakeDb:
    """Just enough of the database for the poller's decisions."""

    def __init__(self, *, workspaces=None, handled=(), active_triggers=0):
        self.workspaces = list(
            workspaces if workspaces is not None else [{"id": 1, "active_sessions": 0, "base_branch": "main"}]
        )
        self.handled = set(handled)
        self.active_triggers = active_triggers
        self.created: list[dict] = []
        self.next_id = 100

    def install(self, monkeypatch):
        async def count_active_trigger_sessions():
            return self.active_triggers

        async def handled_trigger_refs(refs, since):
            return {ref for ref in refs if ref in self.handled}

        async def list_workspaces():
            return list(self.workspaces)

        async def create_workspace(*, name, base_branch, created_by):
            if any(w.get("name") == name for w in self.workspaces):
                raise ValueError(f"workspace '{name}' already exists")
            entry = {
                "id": max((w["id"] for w in self.workspaces), default=0) + 1,
                "name": name,
                "active_sessions": 0,
                "base_branch": base_branch,
            }
            self.workspaces.append(entry)
            return entry

        async def set_workspace_base_branch(workspace_id, base_branch):
            for workspace in self.workspaces:
                if workspace["id"] == workspace_id:
                    workspace["base_branch"] = base_branch

        async def create_session(**kwargs):
            self.created.append(kwargs)
            self.handled.add(kwargs["trigger_ref"])
            self.active_triggers += 1
            self.next_id += 1
            return self.next_id

        monkeypatch.setattr(triggers.db, "count_active_trigger_sessions", count_active_trigger_sessions)
        monkeypatch.setattr(triggers.db, "handled_trigger_refs", handled_trigger_refs)
        monkeypatch.setattr(triggers.db, "list_workspaces", list_workspaces)
        monkeypatch.setattr(triggers.db, "create_workspace", create_workspace)
        monkeypatch.setattr(triggers.db, "set_workspace_base_branch", set_workspace_base_branch)
        monkeypatch.setattr(triggers.db, "create_session", create_session)


def allow_models(monkeypatch, ok: bool = True):
    class Policy:
        def __init__(self):
            self.ok = ok
            self.detail = "test policy"

    monkeypatch.setattr(triggers.model_policy, "current", lambda: Policy())


class TestPolling:
    @pytest.mark.asyncio
    async def test_an_opened_issue_becomes_a_session(self, monkeypatch):
        FakeRepo(issues=[issue(812)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        created = fake_db.created[0]
        assert created["trigger_ref"] == "issue-812"
        assert created["trigger_kind"] == "issue"
        assert "Issue #812" in created["task"]
        # A self-queued session never touches a shared environment.
        assert created["deploy_to_dev"] is False
        assert created["open_pull_request"] is True

    @pytest.mark.asyncio
    async def test_the_same_issue_is_not_queued_twice(self, monkeypatch):
        FakeRepo(issues=[issue(812)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        poller = triggers.TriggerPoller()

        await poller.poll_once()
        # The second pass sees the same repository state; the reference is
        # what makes it a no-op, not the moving time window.
        second = await poller.poll_once()

        assert second == []
        assert len(fake_db.created) == 1

    @pytest.mark.asyncio
    async def test_a_review_asking_for_changes_becomes_a_session(self, monkeypatch):
        FakeRepo(
            pulls=[{"number": 772, "title": "Add an agent runner", "pull_request": {}}],
            reviews={772: [review(5085681761)]},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        created = fake_db.created[0]
        assert created["trigger_ref"] == "pr-772-review-5085681761"
        assert created["trigger_kind"] == "review"
        assert "#772" in created["task"]
        assert "Please fix X." in created["task"]
        # The work belongs on the pull request's own branch, and updating it
        # is not opening another pull request.
        assert created["branch"] == "agent/pr/session-772"
        assert created["open_pull_request"] is False

    @pytest.mark.asyncio
    async def test_an_approval_is_not_work(self, monkeypatch):
        FakeRepo(
            pulls=[{"number": 772, "title": "Add an agent runner", "pull_request": {}}],
            reviews={772: [review(1, state="APPROVED"), review(2, state="COMMENTED")]},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    @pytest.mark.asyncio
    async def test_a_pull_request_is_not_treated_as_an_issue(self, monkeypatch):
        # The issues endpoint returns pull requests too; `labelled_issues`
        # filters them, and this is the guard that keeps that filtering
        # honest if the endpoint changes.
        FakeRepo(issues=[], pulls=[{"number": 772, "title": "PR", "pull_request": {}}]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []


class TestBounds:
    @pytest.mark.asyncio
    async def test_the_automation_stops_at_its_own_ceiling(self, monkeypatch):
        FakeRepo(issues=[issue(1), issue(2), issue(3)]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": i, "active_sessions": 0, "base_branch": "main"} for i in range(1, 6)])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(triggers, "settings", replace(triggers.settings, max_parallel_sessions=4))

        queued = await triggers.TriggerPoller().poll_once()

        # Half the parallel ceiling, so an operator always has room.
        assert triggers.max_active_sessions() == 2
        assert len(queued) == 2

    @pytest.mark.asyncio
    async def test_nothing_is_queued_while_the_ceiling_is_full(self, monkeypatch):
        repo = FakeRepo(issues=[issue(1)])
        repo.install(monkeypatch)
        fake_db = FakeDb(active_triggers=99)
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    @pytest.mark.asyncio
    async def test_a_cloud_capable_key_queues_nothing(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch, ok=False)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []


class TestWorkspaces:
    @pytest.mark.asyncio
    async def test_a_workspace_is_created_when_all_are_busy(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": 1, "active_sessions": 1, "base_branch": "main"}])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        assert len(fake_db.workspaces) == 2
        assert fake_db.created[0]["workspace_id"] == 2

    @pytest.mark.asyncio
    async def test_no_workspace_beyond_the_parallel_ceiling(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": i, "active_sessions": 1, "base_branch": "main"} for i in range(1, 4)])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(triggers, "settings", replace(triggers.settings, max_parallel_sessions=3))

        assert await triggers.TriggerPoller().poll_once() == []
        # A fourth workspace could never run anything, so it is not created.
        assert len(fake_db.workspaces) == 3

    @pytest.mark.asyncio
    async def test_a_free_workspace_is_reused(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": 7, "active_sessions": 0, "base_branch": "main"}])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert len(fake_db.workspaces) == 1
        assert fake_db.created[0]["workspace_id"] == 7


class TestWindow:
    @pytest.mark.asyncio
    async def test_a_failing_pass_does_not_move_the_window(self, monkeypatch):
        async def boom(*_args, **_kwargs):
            raise RuntimeError("GitHub is down")

        monkeypatch.setattr(triggers.github, "labelled_issues", boom)
        FakeDb().install(monkeypatch)
        allow_models(monkeypatch)
        poller = triggers.TriggerPoller()
        before = poller._since

        with pytest.raises(RuntimeError):
            await poller.poll_once()

        # Otherwise the reviews submitted during the outage would fall out of
        # the window and never be seen.
        assert poller._since == before

    @pytest.mark.asyncio
    async def test_the_window_holds_while_a_candidate_is_deferred(self, monkeypatch):
        # The ceiling stops the third issue from being queued. The listings
        # filter by the window, so moving it past that issue would drop the
        # work for good instead of deferring it to the next pass.
        FakeRepo(issues=[issue(1), issue(2), issue(3)]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": i, "active_sessions": 0, "base_branch": "main"} for i in range(1, 6)])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(triggers, "settings", replace(triggers.settings, max_parallel_sessions=4))
        poller = triggers.TriggerPoller()
        before = poller._since

        queued = await poller.poll_once()

        assert len(queued) == 2
        assert poller._since == before

    @pytest.mark.asyncio
    async def test_the_window_holds_when_no_workspace_is_free(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": i, "active_sessions": 1, "base_branch": "main"} for i in range(1, 4)])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(triggers, "settings", replace(triggers.settings, max_parallel_sessions=3))
        poller = triggers.TriggerPoller()
        before = poller._since

        assert await poller.poll_once() == []
        assert poller._since == before

    @pytest.mark.asyncio
    async def test_the_window_advances_once_everything_was_handled(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        FakeDb().install(monkeypatch)
        allow_models(monkeypatch)
        poller = triggers.TriggerPoller()
        before = poller._since

        await poller.poll_once()

        assert poller._since > before

    @pytest.mark.asyncio
    async def test_the_first_pass_looks_back_a_bounded_distance(self):
        poller = triggers.TriggerPoller()
        age = datetime.now(timezone.utc) - poller._since
        assert timedelta(hours=5) < age < timedelta(hours=7)


class TestReviewSessionsUpdateTheirPullRequest:
    """A review is answered on the pull request it was written on.

    Anything else — a second pull request, a push to somebody's branch —
    is either useless or not the runner's to do.
    """

    @pytest.mark.asyncio
    async def test_the_session_is_queued_on_the_pull_request_branch(self, monkeypatch):
        FakeRepo(
            pulls=[{"number": 772, "title": "Add an agent runner", "pull_request": {}}],
            reviews={772: [review(11)]},
            heads={772: ("agent/agent-runner/session-3", "ls1intum/edutelligence")},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["branch"] == "agent/agent-runner/session-3"
        assert created["open_pull_request"] is False
        # And the workspace it runs in starts from that branch, so the agent
        # sees the pull request's current state rather than main.
        workspace = next(w for w in fake_db.workspaces if w["id"] == created["workspace_id"])
        assert workspace["base_branch"] == "agent/agent-runner/session-3"

    @pytest.mark.asyncio
    async def test_a_fork_head_is_not_touched(self, monkeypatch):
        FakeRepo(
            pulls=[{"number": 900, "title": "From a fork", "pull_request": {}}],
            reviews={900: [review(12)]},
            heads={900: ("feature", "someone/edutelligence")},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    @pytest.mark.asyncio
    async def test_a_human_branch_is_left_to_its_author(self, monkeypatch):
        FakeRepo(
            pulls=[{"number": 864, "title": "Someone's work", "pull_request": {}}],
            reviews={864: [review(13)]},
            heads={864: ("logos/issue-651-lacq-auto-set", "ls1intum/edutelligence")},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        # The branch rules exist to keep agent pushes off human branches;
        # answering such a review is a person's job.
        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    @pytest.mark.asyncio
    async def test_inline_comments_are_part_of_the_task(self, monkeypatch):
        # Most changes-requested reviews say nothing in the body and
        # everything inline; a task built from the body alone asks the agent
        # to fix nothing in particular.
        FakeRepo(
            pulls=[{"number": 772, "title": "Add an agent runner", "pull_request": {}}],
            reviews={772: [review(14, body="")]},
            comments={
                (772, 14): [
                    {"path": "app/sessions.py", "line": 420, "body": "This can strand a session."},
                    {"path": "app/github.py", "original_line": 350, "body": "Paginate this."},
                ]
            },
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        task = fake_db.created[0]["task"]
        assert "app/sessions.py:420" in task
        assert "This can strand a session." in task
        assert "app/github.py:350" in task
        assert "Paginate this." in task


class TestWorkspaceNaming:
    def test_the_lowest_unused_name_is_taken(self):
        # Counting workspaces repeats a name after a deletion, and every
        # later poll would hit the same conflict and defer work.
        assert triggers._next_auto_name(set()) == "auto-1"
        assert triggers._next_auto_name({"auto-1", "auto-3"}) == "auto-2"
        assert triggers._next_auto_name({"auto-1", "auto-2"}) == "auto-3"

    @pytest.mark.asyncio
    async def test_a_deleted_workspace_does_not_block_the_next_poll(self, monkeypatch):
        FakeRepo(issues=[issue(1)]).install(monkeypatch)
        # 'auto-2' was deleted; the remaining names would make a counting
        # scheme propose 'auto-3', which exists and is busy.
        fake_db = FakeDb(
            workspaces=[
                {"id": 1, "name": "auto-1", "active_sessions": 1, "base_branch": "main"},
                {"id": 3, "name": "auto-3", "active_sessions": 1, "base_branch": "main"},
            ]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        assert any(w.get("name") == "auto-2" for w in fake_db.workspaces)

    @pytest.mark.asyncio
    async def test_a_full_pool_repoints_a_free_workspace(self, monkeypatch):
        FakeRepo(
            pulls=[{"number": 772, "title": "Add an agent runner", "pull_request": {}}],
            reviews={772: [review(15)]},
            heads={772: ("agent/agent-runner/session-3", "ls1intum/edutelligence")},
        ).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": 1, "name": "auto-1", "active_sessions": 0, "base_branch": "main"}])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(triggers, "settings", replace(triggers.settings, max_parallel_sessions=1))

        queued = await triggers.TriggerPoller().poll_once()

        # No room for another workspace, so the free one follows the branch
        # instead of the work being deferred forever.
        assert len(queued) == 1
        assert fake_db.workspaces[0]["base_branch"] == "agent/agent-runner/session-3"
