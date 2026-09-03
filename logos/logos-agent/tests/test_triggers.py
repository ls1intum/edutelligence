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
from app import controls, triggers

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


def comment(
    comment_id: int,
    number: int,
    body: str,
    author: str = "wasnertobias",
    *,
    path: str | None = None,
    root: int | None = None,
    minutes_ago: int = 5,
) -> dict:
    made = {
        "id": comment_id,
        "body": body,
        "user": {"login": author},
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z"),
        "in_reply_to_id": root,
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
        writers=("wasnertobias",),
        conversation=None,
    ):
        self.conversation = conversation or []
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
        # Who may write to the repository. Anybody may comment on a public
        # one; only these may direct a change to it.
        self.writers = {w.lower() for w in writers}

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

        async def may_push(login):
            return login.lower() in self.writers

        async def pull_request_conversation(number, limit=40):
            return list(self.conversation)

        for name, fn in [
            ("pull_request_conversation", pull_request_conversation),
            ("assigned_issues", assigned_issues),
            ("assigned_pull_requests", assigned_pull_requests),
            ("authored_pull_requests", authored_pull_requests),
            ("latest_changes_requested_review", latest_changes_requested_review),
            ("review_comments", review_comments),
            ("pull_request", pull_request),
            ("recent_issue_comments", recent_issue_comments),
            ("recent_review_comments", recent_review_comments),
            ("react", react),
            ("may_push", may_push),
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
        self.comment_mark = None

    def install(self, monkeypatch):
        async def count_active_trigger_sessions():
            return self.active_triggers

        async def handled_trigger_refs(refs):
            return {ref for ref in refs if ref in self.handled}

        async def list_workspaces():
            return list(self.workspaces)

        async def create_workspace(*, name, base_branch, created_by, ephemeral=False):
            if any(w.get("name") == name for w in self.workspaces):
                raise ValueError(f"workspace '{name}' already exists")
            entry = {
                "id": max((w["id"] for w in self.workspaces), default=0) + 1,
                "name": name,
                "active_sessions": 0,
                "base_branch": base_branch,
                "ephemeral": ephemeral,
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

        async def comments_scanned_at():
            return self.comment_mark

        async def mark_comments_scanned(moment):
            self.comment_mark = moment

        for name, fn in [
            ("comments_scanned_at", comments_scanned_at),
            ("mark_comments_scanned", mark_comments_scanned),
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


def ceiling(monkeypatch, limit: int):
    """Set the ceiling an operator would have set, at runtime."""

    async def stored():
        return {"mode": "running", "mode_reason": "", "max_parallel": limit, "updated_by": "tobias"}

    monkeypatch.setattr(controls.db, "get_controls", stored)
    controls.forget()


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
        assert created["trigger_ref"] == "thread-772-issue-9001"
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
        assert created["trigger_ref"] == "thread-864-issue-9002"
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
        assert created["trigger_ref"] == "thread-772-issue-9003"
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
        ceiling(monkeypatch, 4)

        queued = await triggers.TriggerPoller().poll_once()

        # Half the ceiling *in force*, so an operator always has room — and
        # it follows what they set at runtime, not what the environment
        # configured.
        assert triggers.max_active_sessions(4) == 2
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
        ceiling(monkeypatch, 4)
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


class TestTheCommentMark:
    """Where the comment scan got to, kept across stops.

    A question asked while the runner is paused has to still be there when
    it comes back: nothing else remembers it. An assignment or a review is
    read from the repository's current state on every pass, but a comment
    older than the window is simply gone.
    """

    async def test_a_finished_pass_records_how_far_it_got(self, monkeypatch):
        FakeRepo().install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert fake_db.comment_mark is not None

    async def test_a_stopped_runner_forgets_nothing(self, monkeypatch):
        FakeRepo(assigned_issues=[issue(812)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        async def paused():
            return {"mode": "paused", "mode_reason": "incident", "max_parallel": None, "updated_by": "tobias"}

        monkeypatch.setattr(controls.db, "get_controls", paused)
        controls.forget()

        assert await triggers.TriggerPoller().poll_once() == []
        # Moving the mark here would drop every question asked during the
        # pause out of the window before anyone could answer it.
        assert fake_db.comment_mark is None

    async def test_work_left_for_the_next_pass_holds_the_mark(self, monkeypatch):
        FakeRepo(assigned_issues=[issue(812), issue(813)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)
        ceiling(monkeypatch, 1)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        assert fake_db.comment_mark is None

    async def test_the_window_starts_where_the_last_pass_stopped(self, monkeypatch):
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        now = datetime.now(timezone.utc)
        fake_db.comment_mark = now - timedelta(days=3)

        window = await triggers.TriggerPoller()._comment_window(now)

        # Three days beyond the ordinary lookback, because that is how long
        # the runner was down and those questions are still unanswered.
        assert window == fake_db.comment_mark

    async def test_a_long_absence_does_not_wake_up_to_a_month_of_talk(self, monkeypatch):
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        now = datetime.now(timezone.utc)
        fake_db.comment_mark = now - timedelta(days=90)

        window = await triggers.TriggerPoller()._comment_window(now)

        assert window == now - triggers.MAX_COMMENT_LOOKBACK

    async def test_without_a_mark_the_ordinary_window_applies(self, monkeypatch):
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        now = datetime.now(timezone.utc)

        assert await triggers.TriggerPoller()._comment_window(now) == now - triggers.COMMENT_LOOKBACK


class TestWhatTheAgentIsTold:
    """The sandbox cannot fetch anything, so the task has to carry it."""

    async def test_a_handover_carries_the_review_conversation(self, monkeypatch):
        repo = FakeRepo(
            assigned_pulls=[pull(864, "A change")],
            heads={864: ("logos/agent/x/session-3", REPO)},
            conversation=[
                {
                    "kind": "inline comment",
                    "author": "wasnertobias",
                    "at": datetime.now(timezone.utc),
                    "path": "app/db.py",
                    "line": 42,
                    "state": "",
                    "body": "This lock is taken twice.",
                }
            ],
        )
        repo.install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        task = fake_db.created[0]["task"]
        # Without this the agent reconstructs the review from the diff, which
        # is guesswork dressed up as work.
        assert "This lock is taken twice." in task
        assert "app/db.py:42" in task

    async def test_a_handover_without_a_conversation_still_runs(self, monkeypatch):
        repo = FakeRepo(assigned_pulls=[pull(864)], heads={864: ("logos/agent/x/session-3", REPO)})
        repo.install(monkeypatch)

        async def broken(number, limit=40):
            raise RuntimeError("502")

        monkeypatch.setattr(triggers.github, "pull_request_conversation", broken)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1

    def test_the_task_says_the_conversation_is_complete(self):
        # Otherwise it goes looking for the rest of it through a network it
        # does not have.
        task = triggers.takeover_task(772, "A change", "", "logos/agent/x", "")
        assert "cannot fetch more" in task


class TestWhatTheUiIsTold:
    def test_the_quota_shown_is_the_one_in_force(self):
        # An operator who lowers the ceiling to 2 and still reads "up to 6"
        # on the page has been told a number that decides nothing.
        lowered = triggers.poller.status(2)["max_active_sessions"]
        configured = triggers.poller.status()["max_active_sessions"]

        assert lowered <= 2
        assert lowered <= configured


class TestReactions:
    """What a person sees on the thread they wrote in."""

    async def test_a_queued_request_is_acknowledged(self, monkeypatch):
        repo = FakeRepo(assigned_issues=[issue(812)])
        repo.install(monkeypatch)
        FakeDb().install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert repo.reactions == [(f"/repos/{REPO}/issues/812", triggers.github.REACTION_QUEUED)]

    async def test_nothing_is_acknowledged_that_was_not_queued(self, monkeypatch):
        # The reaction is a promise that the work is in the queue: a refused
        # session must not leave one behind.
        repo = FakeRepo(assigned_issues=[issue(812)])
        repo.install(monkeypatch)
        FakeDb().install(monkeypatch)
        allow_models(monkeypatch, ok=False)

        assert await triggers.TriggerPoller().poll_once() == []
        assert repo.reactions == []

    async def test_the_session_carries_where_to_react_next(self, monkeypatch):
        # The later stages are reacted to by the launcher, in another
        # process and possibly after a restart.
        FakeRepo(assigned_issues=[issue(812)]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert fake_db.created[0]["reaction_target"] == f"/repos/{REPO}/issues/812"


class TestReviewRouting:
    """What a review session is allowed to be queued as at all."""

    async def test_a_review_without_a_writable_branch_is_left_to_a_person(self, monkeypatch):
        # The fix belongs on that pull request's branch. Queued anyway, the
        # session would start from the default branch on a branch of its own
        # and could never update the pull request its task is about.
        FakeRepo(
            authored_pulls=[pull(900)],
            reviews={900: review(1)},
            heads={900: ("feature", "someone/edutelligence")},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    async def test_a_review_is_acknowledged_on_the_pull_request(self, monkeypatch):
        # A submitted review is not a review *comment*: the two id sequences
        # are independent, so reacting to the review id as though it were a
        # comment id would fail silently.
        repo = FakeRepo(authored_pulls=[pull(772)], reviews={772: review(5085681761)})
        repo.install(monkeypatch)
        FakeDb().install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert repo.reactions == [(f"/repos/{REPO}/issues/772", "eyes")]

    async def test_the_reviews_own_comments_do_not_become_a_second_session(self, monkeypatch):
        # The repository-wide comment scan sees the very comments the review
        # task already carries.
        inline = comment(7010, 772, "fix this", path="app/db.py")
        FakeRepo(
            authored_pulls=[pull(772)],
            reviews={772: review(55)},
            review_comments={(772, 55): [inline]},
            inline_comments=[inline],
        ).install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in (1, 2)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        assert fake_db.created[0]["trigger_ref"] == "pr-772-review-55"


class TestInlineThreads:
    async def test_each_inline_thread_is_answered_in_itself(self, monkeypatch):
        # Two line-specific questions on one pull request are two
        # conversations; merging them would answer one and leave the other
        # without a reply.
        FakeRepo(
            authored_pulls=[pull(772)],
            inline_comments=[
                comment(7001, 772, f"@{AGENT} why the lock?", path="app/db.py", root=None),
                comment(7002, 772, f"@{AGENT} and here?", path="app/github.py", root=None),
            ],
        ).install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in (1, 2, 3)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 2
        targets = {c["reply_target"] for c in fake_db.created}
        assert targets == {"review_comment:772:7001", "review_comment:772:7002"}

    async def test_a_reply_joins_the_thread_it_answers(self, monkeypatch):
        # A reply carries the root's id; both belong to one conversation.
        FakeRepo(
            authored_pulls=[pull(772)],
            inline_comments=[
                comment(7001, 772, "why the lock?", path="app/db.py", root=None, minutes_ago=20),
                comment(7005, 772, "…and does it cover restarts?", path="app/db.py", root=7001, minutes_ago=5),
            ],
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        queued = await triggers.TriggerPoller().poll_once()

        assert len(queued) == 1
        created = fake_db.created[0]
        assert created["reply_target"] == "review_comment:772:7001"
        assert created["trigger_ref"] == "thread-772-inline-7001-7005"

    async def test_the_newest_comment_is_the_newest_by_time(self, monkeypatch):
        # Issue and review comments have independent id sequences, so a
        # newer comment can carry a smaller id.
        FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[
                comment(9000, 772, "older, but a bigger number", minutes_ago=60),
                comment(10, 772, "newer, with a smaller one", minutes_ago=1),
            ],
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert fake_db.created[0]["trigger_ref"] == "thread-772-issue-10"


class TestWhoMayDirectChanges:
    """Anybody may ask; not everybody may have code written for them.

    On a public repository the comment box is open to the world, and a
    session that commits does so with the runner's credentials. What decides
    is the repository's own permissions, not the ability to type.
    """

    async def test_an_outsider_gets_an_answer_but_no_branch(self, monkeypatch):
        FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[comment(9100, 772, f"@{AGENT} could you rewrite this?", "passer-by")],
            writers=("wasnertobias",),
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = fake_db.created[0]
        assert created["branch"] is None
        assert created["reply_target"] == "issue:772"

    async def test_a_collaborator_may_ask_for_a_change(self, monkeypatch):
        FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[comment(9101, 772, "please also handle the empty case", "wasnertobias")],
            heads={772: ("logos/agent/x/session-1", REPO)},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert fake_db.created[0]["branch"] == "logos/agent/x/session-1"

    async def test_one_writer_in_the_thread_is_enough(self, monkeypatch):
        # A maintainer answering a passer-by is still a maintainer asking.
        FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[
                comment(9102, 772, f"@{AGENT} what about X?", "passer-by", minutes_ago=30),
                comment(9103, 772, "good point — please do that", "wasnertobias", minutes_ago=5),
            ],
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert fake_db.created[0]["branch"] is not None

    async def test_a_review_from_outside_the_repository_is_left_to_a_person(self, monkeypatch):
        # A review is a request to change code. From somebody who cannot
        # push, acting on it would let a stranger direct what is committed.
        outside = review(77)
        outside["user"] = {"login": "passer-by"}
        FakeRepo(authored_pulls=[pull(772)], reviews={772: outside}).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    async def test_permissions_are_looked_up_once_per_pass(self, monkeypatch):
        repo = FakeRepo(
            authored_pulls=[pull(772)],
            issue_comments=[comment(9104 + i, 772, f"note {i}", "wasnertobias") for i in range(4)],
        )
        repo.install(monkeypatch)
        looked_up: list = []
        original = triggers.github.may_push

        async def counting(login):
            looked_up.append(login)
            return await original(login)

        monkeypatch.setattr(triggers.github, "may_push", counting)
        FakeDb().install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert looked_up == ["wasnertobias"]


class TestWorkspaceNames:
    """A workspace name is read by people, and lands in the branch."""

    def test_an_issue_workspace_says_which_issue(self):
        assert triggers.workspace_name("issue", 812, "OOM on startup") == "issue-812-oom-on-startup"

    def test_a_long_title_is_trimmed_rather_than_dumped(self):
        name = triggers.workspace_name("issue", 5, "Refactor the whole scheduling pipeline for clarity and speed")
        # It becomes part of `logos/agent/<name>/session-42`, so it stays
        # readable rather than complete.
        assert len(name) < 60
        assert name.startswith("issue-5-refactor")

    def test_punctuation_does_not_reach_a_volume_or_a_branch_name(self):
        name = triggers.workspace_name("issue", 9, "Fix: don't crash (again)!")
        assert all(c.isalnum() or c == "-" for c in name)

    def test_a_titleless_thread_still_names_its_number(self):
        assert triggers.workspace_name("pr", 772, "") == "pr-772"

    async def test_a_triggered_workspace_is_named_after_its_work(self, monkeypatch):
        FakeRepo(assigned_issues=[issue(812, title="OOM on startup")]).install(monkeypatch)
        fake_db = FakeDb(workspaces=[{"id": 1, "name": "taken", "active_sessions": 1, "base_branch": "main"}])
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        created = [w for w in fake_db.workspaces if w["name"] != "taken"]
        assert created[0]["name"] == "issue-812-oom-on-startup"
        # And it is the runner's to clean up when the work is done.
        assert created[0]["ephemeral"] is True


class TestUrgency:
    async def test_a_security_issue_is_queued_above_a_documentation_one(self, monkeypatch):
        FakeRepo(
            assigned_issues=[
                dict(issue(1, title="typo"), labels=[{"name": "documentation"}]),
                dict(issue(2, title="token leak"), labels=[{"name": "security fix"}]),
            ]
        ).install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in (1, 2, 3)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        # Both fit here; what matters is which one the queue offers first,
        # since a busy platform only admits one per capacity reading.
        assert [c["trigger_ref"] for c in fake_db.created] == ["issue-2", "issue-1"]
        assert fake_db.created[0]["priority"] > fake_db.created[1]["priority"]
        assert "security" in fake_db.created[0]["priority_reason"]

    async def test_blocked_work_is_not_started(self, monkeypatch):
        FakeRepo(assigned_issues=[dict(issue(3), labels=[{"name": "blocked"}])]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    async def test_a_review_carries_more_urgency_than_a_fresh_issue(self, monkeypatch):
        FakeRepo(
            assigned_issues=[issue(1)],
            authored_pulls=[pull(772)],
            reviews={772: review(9)},
        ).install(monkeypatch)
        fake_db = FakeDb(
            workspaces=[{"id": i, "name": f"w{i}", "active_sessions": 0, "base_branch": "main"} for i in (1, 2, 3)]
        )
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        await triggers.TriggerPoller().poll_once()

        assert fake_db.created[0]["trigger_ref"] == "pr-772-review-9"


class TestTaskConventions:
    """Every task carries what a new colleague would be told."""

    def test_each_kind_of_task_carries_the_house_rules(self):
        tasks = [
            triggers.issue_task(issue(1)),
            triggers.takeover_task(2, "t", "b", "logos/agent/x"),
            triggers.review_task(3, "t", review(1), []),
            triggers.thread_task(4, "t", [{"body": "q", "user": {"login": "a"}}], branch=None),
        ]
        for task in tasks:
            assert "How work is done here" in task
            assert "Never merge a pull request" in task
            assert "fails on the unfixed code" in task


class TestRefusalAppliesToEveryKind:
    """`blocked` is an answer, whatever kind of work carries it."""

    async def test_a_blocked_pull_request_is_not_taken_over(self, monkeypatch):
        FakeRepo(assigned_pulls=[dict(pull(864), labels=[{"name": "blocked"}])]).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
        assert fake_db.created == []

    async def test_a_review_on_a_blocked_pull_request_is_not_worked(self, monkeypatch):
        FakeRepo(
            authored_pulls=[dict(pull(772), labels=[{"name": "wontfix"}])],
            reviews={772: review(5)},
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []

    async def test_a_question_on_a_stale_thread_is_left_alone(self, monkeypatch):
        FakeRepo(
            authored_pulls=[dict(pull(772), labels=[{"name": "stale"}])],
            issue_comments=[comment(9200, 772, f"@{AGENT} still relevant?")],
        ).install(monkeypatch)
        fake_db = FakeDb()
        fake_db.install(monkeypatch)
        allow_models(monkeypatch)

        assert await triggers.TriggerPoller().poll_once() == []
