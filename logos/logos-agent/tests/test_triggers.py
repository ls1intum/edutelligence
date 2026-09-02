"""Tests for using the agent's account the way you use a colleague's.

The interesting properties are not that a poll queues something. They are
that assigning something twice does not produce two pull requests, that a
question on somebody else's branch is answered rather than pushed to, that
bots do not start a stampede, and that a taken-over pull request keeps its
own branch name.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from app import triggers

AGENT = "LogosOSSAgent"
REPO = "ls1intum/edutelligence"


def issue(number: int, title: str = "Something is wrong", body: str = "Details.") -> dict:
    return {"number": number, "title": title, "body": body}


def pull(number: int, title: str = "A change", body: str = "What it does.") -> dict:
    return {"number": number, "title": title, "body": body, "pull_request": {}}


def review(review_id: int, state: str = "CHANGES_REQUESTED", body: str = "Please fix X.") -> dict:
    return {
        "id": review_id,
        "state": state,
        "body": body,
        "user": {"login": "wasnertobias"},
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


def comment(comment_id: int, number: int, body: str, author: str = "wasnertobias", *, path: str | None = None) -> dict:
    made = {
        "id": comment_id,
        "body": body,
        "user": {"login": author},
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{number}",
        "pull_request_url": f"https://api.github.com/repos/{REPO}/pulls/{number}",
    }
    if path:
        made["path"] = path
        made["line"] = 42
    return made


class FakeRepo:
    """The repository as the poller sees it."""

    def __init__(
        self,
        assigned_issues=None,
        assigned_pulls=None,
        authored_pulls=None,
        reviews=None,
        heads=None,
        review_comments=None,
        issue_comments=None,
        inline_comments=None,
    ):
        self.assigned_issues = assigned_issues or []
        self.assigned_pulls = assigned_pulls or []
        self.authored_pulls = authored_pulls or []
        self.reviews = reviews or {}
        # Per pull request: (head ref, head repository). Defaults to an agent
        # branch in this repository.
        self.heads = heads or {}
        self.review_comments = review_comments or {}
        self.issue_comments = issue_comments or []
        self.inline_comments = inline_comments or []
        self.reactions: list = []

    def install(self, monkeypatch):
        async def assigned_issues(_login):
            return self.assigned_issues

        async def assigned_pull_requests(_login):
            return self.assigned_pulls

        async def authored_pull_requests(_login):
            return self.authored_pulls

        async def latest_changes_requested_review(number):
            return self.reviews.get(number)

        async def review_comments(number, review_id):
            return self.review_comments.get((number, review_id), [])

        async def pull_request(number):
            ref, repo = self.heads.get(number, (f"logos/agent/pr/session-{number}", REPO))
            return {"number": number, "head": {"ref": ref, "repo": {"full_name": repo}}}

        async def recent_issue_comments(_since):
            return self.issue_comments

        async def recent_review_comments(_since):
            return self.inline_comments

        async def react(path, content="eyes"):
            self.reactions.append((path, content))
            return True

        for name, fn in [
            ("assigned_issues", assigned_issues),
            ("assigned_pull_requests", assigned_pull_requests),
            ("authored_pull_requests", authored_pull_requests),
            ("latest_changes_requested_review", latest_changes_requested_review),
            ("review_comments", review_comments),
            ("pull_request", pull_request),
            ("recent_issue_comments", recent_issue_comments),
            ("recent_review_comments", recent_review_comments),
            ("react", react),
        ]:
            monkeypatch.setattr(triggers.github, name, fn)


class FakeDb:
    """Just enough of the database for the poller's decisions."""

    def __init__(self, *, workspaces=None, handled=(), active_triggers=0):
        self.workspaces = list(
            workspaces
            if workspaces is not None
            else [{"id": 1, "name": "auto-1", "active_sessions": 0, "base_branch": "main"}]
        )
        self.handled = set(handled)
        self.active_triggers = active_triggers
        self.created: list[dict] = []
        self.next_id = 100

    def install(self, monkeypatch):
        async def count_active_trigger_sessions():
            return self.active_triggers

        async def handled_trigger_refs(refs):
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

        for name, fn in [
            ("count_active_trigger_sessions", count_active_trigger_sessions),
            ("handled_trigger_refs", handled_trigger_refs),
            ("list_workspaces", list_workspaces),
            ("create_workspace", create_workspace),
            ("set_workspace_base_branch", set_workspace_base_branch),
            ("create_session", create_session),
        ]:
            monkeypatch.setattr(triggers.db, name, fn)


def allow_models(monkeypatch, ok: bool = True):
    class Policy:
        def __init__(self):
            self.ok = ok
            self.detail = "test policy"

    monkeypatch.setattr(triggers.model_policy, "current", lambda: Policy())


def agent_account(monkeypatch):
    monkeypatch.setattr(triggers, "settings", replace(triggers.settings, github_login=AGENT, repo_slug=REPO))


@pytest.fixture(autouse=True)
def _account(monkeypatch):
    agent_account(monkeypatch)


class TestAssignment:
    async def test_an_assigned_issue_becomes_work(self, monkeypatch):
        repo = FakeRepo(assigned_issues=[issue(812)])
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        created = fake_db.created[0]
        assert created["trigger_ref"] == "issue-812"
        assert created["trigger_kind"] == "issue"
        assert "issue #812" in created["task"]
        # New work: its own branch, and a pull request to show it in.
        assert created["branch"] is None
        assert created["open_pull_request"] is True
        # And the person who assigned it sees that it landed.
        assert repo.reactions == [(f"/repos/{REPO}/issues/812", "eyes")]

    async def test_an_assigned_pull_request_is_taken_over_on_its_own_branch(self, monkeypatch):
        repo = FakeRepo(
            assigned_pulls=[pull(864, title="Someone's work")],
            heads={864: ("logos/issue-651-lacq-auto-set", REPO)},
        )
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["trigger_ref"] == "pr-864-assigned"
        assert created["trigger_kind"] == "takeover"
        # A person's branch, kept as it is: renaming it would abandon the
        # pull request it belongs to.
        assert created["branch"] == "logos/issue-651-lacq-auto-set"
        assert created["open_pull_request"] is False
        workspace = next(w for w in fake_db.workspaces if w["id"] == created["workspace_id"])
        assert workspace["base_branch"] == "logos/issue-651-lacq-auto-set"

    async def test_the_same_assignment_is_not_worked_twice(self, monkeypatch):
        # An issue that simply stays assigned must not produce a second pull
        # request on the next pass, or next week.
        FakeRepo(assigned_issues=[issue(812)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        poller = triggers.TriggerPoller()

        await poller.poll_once()
        assert await poller.poll_once() == []
        assert len(fake_db.created) == 1

    async def test_a_fork_head_is_not_touched(self, monkeypatch):
        FakeRepo(assigned_pulls=[pull(900)], heads={900: ("feature", "someone/edutelligence")}).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    async def test_a_protected_branch_is_refused(self, monkeypatch):
        FakeRepo(assigned_pulls=[pull(901)], heads={901: ("main", REPO)}).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []


class TestReviews:
    async def test_a_review_on_its_own_pull_request_is_addressed(self, monkeypatch):
        repo = FakeRepo(
            authored_pulls=[pull(772, title="Add an agent runner")],
            reviews={772: review(5085681761)},
            review_comments={(772, 5085681761): [{"path": "app/sessions.py", "line": 420, "body": "This strands."}]},
            heads={772: ("logos/agent/agent-runner/session-3", REPO)},
        )
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["trigger_ref"] == "pr-772-review-5085681761"
        assert created["branch"] == "logos/agent/agent-runner/session-3"
        assert created["open_pull_request"] is False
        # The inline comments are where a changes-requested review keeps its
        # substance.
        assert "app/sessions.py:420" in created["task"]
        assert "This strands." in created["task"]
        # And the answer has somewhere to go.
        assert created["reply_target"] == "issue:772"

    async def test_an_approval_is_not_work(self, monkeypatch):
        FakeRepo(authored_pulls=[pull(772)], reviews={}).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []

    async def test_a_new_review_on_the_same_pull_request_is_new_work(self, monkeypatch):
        repo = FakeRepo(authored_pulls=[pull(772)], reviews={772: review(1)})
        repo.install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in (1, 2)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        poller = triggers.TriggerPoller()

        await poller.poll_once()
        # The reviewer looked again and asked for more.
        repo.reviews[772] = review(2)
        fake_db.active_triggers = 0
        await poller.poll_once()

        assert [c["trigger_ref"] for c in fake_db.created] == ["pr-772-review-1", "pr-772-review-2"]


class TestConversation:
    async def test_a_comment_on_its_pull_request_is_answered(self, monkeypatch):
        repo = FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[comment(9001, 772, "Why does this need a lock?")],
            heads={772: ("logos/agent/x/session-1", REPO)},
        )
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["trigger_ref"] == "thread-772-9001"
        assert created["trigger_kind"] == "comment"
        assert "Why does this need a lock?" in created["task"]
        assert created["reply_target"] == "issue:772"
        assert repo.reactions == [(f"/repos/{REPO}/issues/comments/9001", "eyes")]

    async def test_a_mention_elsewhere_is_answered_without_pushing(self, monkeypatch):
        # Somebody else's pull request: the agent may answer, it may not
        # write to their branch.
        repo = FakeRepo(issue_comments=[comment(9002, 864, f"@{AGENT} short question about this")])
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["trigger_ref"] == "thread-864-9002"
        assert created["branch"] is None
        assert created["open_pull_request"] is False
        assert "Answer in words" in created["task"] or "answer in words" in created["task"].lower()

    async def test_an_inline_question_is_answered_inline(self, monkeypatch):
        repo = FakeRepo(
            authored_pulls=[pull(772)],
            inline_comments=[comment(7001, 772, f"@{AGENT} is this covered?", path="app/db.py")],
        )
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["reply_target"] == "review_comment:772:7001"
        assert repo.reactions == [(f"/repos/{REPO}/pulls/comments/7001", "eyes")]

    async def test_several_comments_in_a_row_are_one_answer(self, monkeypatch):
        # A person writing three notes is asking one thing; three sessions
        # writing to one branch would not be an answer.
        repo = FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[
                comment(9001, 772, "first thought"),
                comment(9002, 772, "and another"),
                comment(9003, 772, "and finally this"),
            ],
        )
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        created = fake_db.created[0]
        assert created["trigger_ref"] == "thread-772-9003"
        for text in ("first thought", "and another", "and finally this"):
            assert text in created["task"]

    async def test_its_own_comments_are_not_a_conversation_with_itself(self, monkeypatch):
        FakeRepo(authored_pulls=[pull(772)], issue_comments=[comment(9004, 772, "Fixed on abc123.", AGENT)]).install(
            monkeypatch
        )
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []

    async def test_bots_do_not_start_a_stampede(self, monkeypatch):
        FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[comment(9005, 772, "12 findings", "coderabbitai[bot]")],
            inline_comments=[comment(7002, 772, "nitpick", "github-actions[bot]", path="x.py")],
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []

    async def test_an_unrelated_comment_without_a_mention_is_none_of_its_business(self, monkeypatch):
        FakeRepo(issue_comments=[comment(9006, 999, "two colleagues talking")]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []


class TestMentionMatching:
    def test_the_account_is_matched_case_insensitively(self):
        assert triggers.mentions_agent(f"hey @{AGENT.lower()} could you look")

    def test_a_longer_name_is_not_this_account(self):
        assert not triggers.mentions_agent(f"@{AGENT}Bot is a different account")

    def test_no_mention_is_no_mention(self):
        assert not triggers.mentions_agent("nothing to do with anyone")

    def test_bots_are_recognised(self):
        assert triggers.is_bot("coderabbitai[bot]")
        assert triggers.is_bot("github-actions")
        assert not triggers.is_bot("wasnertobias")


class TestBounds:
    async def test_the_automation_stops_at_its_own_ceiling(self, monkeypatch):
        FakeRepo(assigned_issues=[issue(1), issue(2), issue(3)]).install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in range(1, 6)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(
            triggers,
            "settings",
            replace(triggers.settings, github_login=AGENT, repo_slug=REPO, max_parallel_sessions=4),
        )

        queued = await triggers.TriggerPoller().poll_once()

        # Half the parallel ceiling, so an operator always has room.
        assert triggers.max_active_sessions() == 2
        assert len(queued) == 2

    async def test_nothing_is_queued_while_the_ceiling_is_full(self, monkeypatch):
        FakeRepo(assigned_issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb(active_triggers=99)
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []

    async def test_a_cloud_capable_key_queues_nothing(self, monkeypatch):
        FakeRepo(assigned_issues=[issue(1)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch, ok=False)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    async def test_what_does_not_fit_now_is_found_again(self, monkeypatch):
        # Nothing is consumed by being seen: a pass reads the repository's
        # current state, so what it could not take on is still there.
        repo = FakeRepo(assigned_issues=[issue(1), issue(2), issue(3)])
        repo.install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in range(1, 6)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(
            triggers,
            "settings",
            replace(triggers.settings, github_login=AGENT, repo_slug=REPO, max_parallel_sessions=4),
        )
        poller = triggers.TriggerPoller()

        first = await poller.poll_once()
        fake_db.active_triggers = 0  # the first two finished
        second = await poller.poll_once()

        assert len(first) == 2 and len(second) == 1
        assert {c["trigger_ref"] for c in fake_db.created} == {"issue-1", "issue-2", "issue-3"}


class TestWorkspaceNaming:
    def test_the_lowest_unused_name_is_taken(self):
        # Counting workspaces repeats a name after a deletion, and every
        # later poll would hit the same conflict and defer work.
        assert triggers._next_auto_name(set()) == "auto-1"
        assert triggers._next_auto_name({"auto-1", "auto-3"}) == "auto-2"

    async def test_a_full_pool_repoints_a_free_workspace(self, monkeypatch):
        FakeRepo(assigned_pulls=[pull(772)], heads={772: ("logos/agent/x/session-3", REPO)}).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": 1, "name": "auto-1", "active_sessions": 0, "base_branch": "main"}])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        monkeypatch.setattr(
            triggers,
            "settings",
            replace(triggers.settings, github_login=AGENT, repo_slug=REPO, max_parallel_sessions=1),
        )

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        assert fake_db.workspaces[0]["base_branch"] == "logos/agent/x/session-3"


class TestCommentWindow:
    def test_comments_are_read_from_a_bounded_window(self):
        # Assignments and reviews are read from the repository's current
        # state; comments are a stream, and without a bound the first pass
        # after a restart would read years of them.
        assert timedelta(hours=12) <= triggers.COMMENT_LOOKBACK <= timedelta(days=2)
