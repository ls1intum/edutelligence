"""The runner's own GitHub calls: dispatch target, image tag, run selection.

These functions build small, fixed HTTP calls; the tests pin the URLs, the
dispatch inputs, and which workflow run counts as "the" build so a refactor
cannot quietly turn the dev deploy into a dispatch of the wrong workflow or
the wrong image tag.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from app import github


@pytest.fixture(autouse=True)
def _clean_verified_login(monkeypatch):
    # verify_identities remembers the API's spelling of the account in the
    # module; every test starts from a service that has not verified yet.
    monkeypatch.setattr(github, "_verified_login", None)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def fake_client(monkeypatch, calls, runs=None):
    """Point github.httpx.AsyncClient at a stub that records every call."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append({"method": "POST", "url": url, "json": json})
            return FakeResponse(201)

        async def get(self, url, headers=None, params=None):
            calls.append({"method": "GET", "url": url, "params": params})
            return FakeResponse(200, {"workflow_runs": runs or []})

    monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(github, "settings", replace(github.settings, github_token="tok"))


def test_pr_number_from_url():
    assert github.pr_number_from_url("https://github.com/ls1intum/edutelligence/pull/772") == 772
    assert github.pr_number_from_url("https://github.com/ls1intum/edutelligence/pull/772/files") == 772
    assert github.pr_number_from_url(None) is None
    assert github.pr_number_from_url("") is None
    assert github.pr_number_from_url("https://github.com/ls1intum/edutelligence/issues/772") is None
    assert github.pr_number_from_url("https://github.com/ls1intum/edutelligence/pull/not-a-number") is None


async def test_dispatch_posts_the_pr_image_tag_on_the_trusted_ref(monkeypatch):
    # The dispatch is what the deploy workflow pulls: the tag must be the one
    # the caller resolved (the PR build's), forwarded as the image-tag input.
    # The ref is the fixed trusted one, never a session branch — the workflow
    # checks out the repository to copy the compose file to the dev host, so
    # a branch ref would let the agent's own compose edits run there.
    calls: list = []
    fake_client(monkeypatch, calls)

    url = await github.dispatch_dev_deploy(image_tag="pr-772")

    post = calls[0]
    assert post["method"] == "POST"
    assert post["url"] == (
        "https://api.github.com/repos/ls1intum/edutelligence/actions/workflows/logos_deploy-dev.yml/dispatches"
    )
    assert post["json"] == {"ref": "main", "inputs": {"image-tag": "pr-772"}}
    assert url.startswith("https://github.com/ls1intum/edutelligence/actions/workflows/logos_deploy-dev.yml")


async def test_wait_for_pr_builds_selects_the_branch_run(monkeypatch):
    # Only the run of the build workflow for this branch counts; an earlier
    # completed run of another branch must not end the wait.
    calls: list = []
    run = {
        "head_branch": "agent/feature-work/session-7",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/1",
    }
    fake_client(
        monkeypatch,
        calls,
        runs=[{"head_branch": "other-branch", "head_sha": "a" * 40, "status": "completed"}, run],
    )

    status, detail = await github.wait_for_pr_builds("agent/feature-work/session-7", "a" * 40)

    assert status == "success"
    assert "actions/runs/1" in detail
    # The polling must be scoped to the build workflow's own runs endpoint:
    # the repository-wide /actions/runs listing has no workflow filter, so a
    # completed run of another workflow on the same branch could otherwise
    # be mistaken for the build.
    assert calls[0]["url"] == (
        "https://api.github.com/repos/ls1intum/edutelligence/actions/workflows/logos_build-and-push-docker.yml/runs"
    )
    assert "workflow_id" not in calls[0]["params"]


async def test_wait_for_pr_builds_ignores_a_completed_run_of_an_earlier_commit(monkeypatch):
    # A retried session force-pushed a new commit onto the same branch.
    # Until GitHub queues the build for the new head, the completed run of
    # the earlier commit is still the newest one on the branch — settling
    # on it would pass the stale pr-<number> image off as the one this
    # commit produced.
    calls: list = []
    branch = "agent/feature-work/session-7"
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {"head_branch": branch, "head_sha": "c" * 40, "status": "in_progress"},
            {
                "head_branch": branch,
                "head_sha": "b" * 40,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/1",
            },
        ],
    )

    status, detail = await github.wait_for_pr_builds(branch, "c" * 40, timeout_s=0.05, poll_s=0.01)

    assert status == "timeout"
    assert "still running" in detail


async def test_wait_for_pr_builds_accepts_the_run_of_the_pushed_commit(monkeypatch):
    # Both commits now have completed runs on the branch; only the one of
    # the pushed sha ends the wait.
    calls: list = []
    branch = "agent/feature-work/session-7"
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {
                "head_branch": branch,
                "head_sha": "c" * 40,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/2",
            },
            {
                "head_branch": branch,
                "head_sha": "b" * 40,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/1",
            },
        ],
    )

    status, detail = await github.wait_for_pr_builds(branch, "c" * 40)

    assert status == "success"
    assert "actions/runs/2" in detail


async def test_wait_for_dev_deploy_ignores_runs_on_session_branches(monkeypatch):
    # Deploys are dispatched on the trusted ref only, so the wait observes
    # runs there: a completed run on a session branch (manual or leftover)
    # must not end the wait, but the completed run on the trusted ref does.
    calls: list = []
    run = {
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/9",
    }
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {"head_branch": "agent/feature-work/session-7", "status": "completed", "conclusion": "success"},
            run,
        ],
    )

    status, detail = await github.wait_for_dev_deploy()

    assert status == "success"
    assert "actions/runs/9" in detail
    # Same scoping as the build wait: the workflow-scoped runs endpoint, so a
    # completed run of another workflow on the same ref is not the deploy.
    assert calls[0]["url"] == (
        "https://api.github.com/repos/ls1intum/edutelligence/actions/workflows/logos_deploy-dev.yml/runs"
    )
    assert "workflow_id" not in calls[0]["params"]


async def test_wait_for_dev_deploy_times_out_without_a_trusted_ref_run(monkeypatch):
    # Without a run on the trusted ref there is no deploy to observe: the
    # wait must time out, not hang, even when session-branch runs completed.
    calls: list = []
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {"head_branch": "agent/feature-work/session-7", "status": "completed", "conclusion": "success"},
            {"head_branch": "other-branch", "status": "in_progress"},
        ],
    )

    status, detail = await github.wait_for_dev_deploy(timeout_s=0.05, poll_s=0.01)

    assert status == "timeout"
    assert "still running" in detail


async def test_latest_dev_deploy_run_id_reads_the_newest_trusted_ref_run(monkeypatch):
    # The marker counts runs on the trusted ref only: a run on a session
    # branch, however new, is not a deploy the environment can be serving.
    calls: list = []
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {"id": 42, "head_branch": "agent/feature-work/session-7", "status": "in_progress"},
            {"id": 41, "head_branch": "main", "status": "completed", "conclusion": "success"},
        ],
    )

    assert await github.latest_dev_deploy_run_id() == 41


async def test_wait_for_dev_deploy_rejects_a_completed_run_from_before_the_dispatch(monkeypatch):
    # The newest completed run on the trusted ref can be a deploy that
    # predates the dispatch: with the pre-dispatch marker the wait must skip
    # it — settling on it would pass the old revision off as the one the
    # session just deployed.
    calls: list = []
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {
                "id": 41,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/41",
            },
        ],
    )

    status, detail = await github.wait_for_dev_deploy(after_run_id=41, timeout_s=0.05, poll_s=0.01)

    assert status == "timeout"
    assert "still running" in detail


async def test_wait_for_dev_deploy_accepts_only_a_run_newer_than_the_marker(monkeypatch):
    # The run the dispatch created is the one newer than the marker: a
    # completed run of an earlier session (older) is skipped even though it
    # is the newest completed one, and the wait ends with the newer run.
    calls: list = []
    fake_client(
        monkeypatch,
        calls,
        runs=[
            {
                "id": 42,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/42",
            },
            {
                "id": 41,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/ls1intum/edutelligence/actions/runs/41",
            },
        ],
    )

    status, detail = await github.wait_for_dev_deploy(after_run_id=41)

    assert status == "success"
    assert "actions/runs/42" in detail


async def test_wait_for_pr_builds_times_out_when_no_build_ran(monkeypatch):
    # Without a pull request (or without logos/** changes) no build run
    # exists for the branch: the wait must time out, not hang, so the caller
    # records the deploy as failed instead of dispatching a stale image.
    calls: list = []
    fake_client(
        monkeypatch, calls, runs=[{"head_branch": "other-branch", "head_sha": "d" * 40, "status": "in_progress"}]
    )

    status, detail = await github.wait_for_pr_builds(
        "agent/feature-work/session-7", "d" * 40, timeout_s=0.05, poll_s=0.01
    )

    assert status == "timeout"
    assert "still running" in detail


class TestAgentIdentity:
    """Every token this service holds must be the agent account's.

    A token belonging to a person would put agent commits, pull requests,
    and deploy dispatches under that person's name — which nothing later can
    undo, so it is checked before the service accepts any work.
    """

    @staticmethod
    def _identity_client(monkeypatch, logins: dict[str, object]):
        """A stub /user endpoint answering per bearer token."""
        seen: list = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None, params=None):
                token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
                seen.append((url, token))
                answer = logins.get(token)
                if answer is None:
                    return FakeResponse(401, {}, text="Bad credentials")
                if isinstance(answer, Exception):
                    raise answer
                return FakeResponse(200, {"login": answer})

        monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
        return seen

    async def test_both_tokens_of_the_agent_account_are_accepted(self, monkeypatch):
        monkeypatch.setattr(
            github,
            "settings",
            replace(
                github.settings,
                github_login="LogosOSSAgent",
                github_token="runner-token",
                session_github_token="session-token",
            ),
        )
        seen = self._identity_client(
            monkeypatch,
            {"runner-token": "LogosOSSAgent", "session-token": "LogosOSSAgent"},
        )

        notes = await github.verify_identities()

        assert len(seen) == 2
        assert all("authenticates as LogosOSSAgent" in note for note in notes)

    async def test_a_token_of_another_account_stops_the_service(self, monkeypatch):
        monkeypatch.setattr(
            github,
            "settings",
            replace(
                github.settings,
                github_login="LogosOSSAgent",
                github_token="runner-token",
                session_github_token="",
            ),
        )
        self._identity_client(monkeypatch, {"runner-token": "wasnertobias"})

        with pytest.raises(github.IdentityError, match="wasnertobias"):
            await github.verify_identities()

    async def test_the_session_token_is_checked_too(self, monkeypatch):
        # The session token is the one that reaches a container, so a
        # mismatch there is the more dangerous of the two.
        monkeypatch.setattr(
            github,
            "settings",
            replace(
                github.settings,
                github_login="LogosOSSAgent",
                github_token="runner-token",
                session_github_token="someone-elses",
            ),
        )
        self._identity_client(
            monkeypatch,
            {"runner-token": "LogosOSSAgent", "someone-elses": "wasnertobias"},
        )

        with pytest.raises(github.IdentityError, match="SESSION_GITHUB_TOKEN"):
            await github.verify_identities()

    async def test_the_account_name_is_matched_case_insensitively(self, monkeypatch):
        monkeypatch.setattr(
            github,
            "settings",
            replace(
                github.settings,
                github_login="logosossagent",
                github_token="runner-token",
                session_github_token="",
            ),
        )
        self._identity_client(monkeypatch, {"runner-token": "LogosOSSAgent"})

        assert await github.verify_identities()
        # The marker lookups compare against the API's spelling, not the
        # configured one, so the differently cased configuration still
        # recognizes its own posted markers.
        assert github._verified_login == "LogosOSSAgent"

    async def test_an_unreachable_api_is_reported_but_does_not_stop_startup(self, monkeypatch):
        # A network blip must not take the service down: the finalizer
        # verifies the same thing inside the container before it pushes.
        monkeypatch.setattr(
            github,
            "settings",
            replace(
                github.settings,
                github_login="LogosOSSAgent",
                github_token="runner-token",
                session_github_token="",
            ),
        )
        self._identity_client(monkeypatch, {"runner-token": RuntimeError("no route to host")})

        notes = await github.verify_identities()

        assert any("could not be verified" in note for note in notes)

    async def test_a_degraded_startup_still_reconciles_the_configured_name(self, monkeypatch):
        # A startup without a reachable API leaves no verified spelling,
        # and the service continues. The supported differently cased
        # configuration must then still recognize its own account's
        # canonical markers, or the retry duplicates the answer.
        monkeypatch.setattr(
            github,
            "settings",
            replace(
                github.settings,
                github_login="logosossagent",
                github_token="runner-token",
                session_github_token="",
            ),
        )
        self._identity_client(monkeypatch, {"runner-token": RuntimeError("no route to host")})

        notes = await github.verify_identities()

        assert any("could not be verified" in note for note in notes)
        assert github._verified_login is None
        comment = {"body": "<!-- logos reply 31 101 -->", "user": {"login": "LogosOSSAgent"}}
        assert github._is_our_marker(comment, "<!-- logos reply 31 101 -->") is True

    async def test_an_unconfigured_token_is_not_a_mismatch(self, monkeypatch):
        monkeypatch.setattr(
            github,
            "settings",
            replace(github.settings, github_login="LogosOSSAgent", github_token="", session_github_token=""),
        )
        self._identity_client(monkeypatch, {})

        notes = await github.verify_identities()

        assert all("is not configured" in note for note in notes)


class TestListingPagination:
    """Long threads must not hide their newest entries.

    These endpoints answer oldest-first and ignore a direction parameter, so
    one page of a pull request with hundreds of reviews contains the oldest
    ones. Reading a single page would miss every new review, permanently.
    """

    @staticmethod
    def _paged_client(monkeypatch, pages: list[list[dict]]):
        requested: list = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None, params=None):
                requested.append(params or {})
                page = int((params or {}).get("page", 1))
                items = pages[page - 1] if page <= len(pages) else []
                return FakeResponse(200, items)

        monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(github, "settings", replace(github.settings, github_token="tok"))
        return requested

    async def test_the_newest_review_is_found_past_the_first_page(self, monkeypatch):
        # The endpoint answers oldest-first and ignores a direction
        # parameter, so on a long-running pull request the review that
        # matters is on the last page, not the first.
        old = [
            {"id": i, "state": "CHANGES_REQUESTED", "submitted_at": "2020-01-01T00:00:00Z", "user": {"login": "a"}}
            for i in range(100)
        ]
        newest = {
            "id": 999,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-09-02T10:00:00Z",
            "user": {"login": "a"},
        }
        requested = self._paged_client(monkeypatch, [old, [newest]])

        review = await github.latest_changes_requested_review(772)

        assert review["id"] == 999
        assert [p["page"] for p in requested] == [1, 2]
        assert all(p["per_page"] == 100 for p in requested)

    async def test_an_approval_is_not_a_request_for_changes(self, monkeypatch):
        requested = self._paged_client(
            monkeypatch, [[{"id": 1, "state": "APPROVED", "submitted_at": "2026-09-02T10:00:00Z"}]]
        )

        assert await github.latest_changes_requested_review(772) is None
        assert len(requested) == 1

    async def test_assigned_listings_are_paginated_too(self, monkeypatch):
        first = [{"number": i, "title": "t"} for i in range(100)]
        second = [{"number": 500, "title": "the newest"}]
        requested = self._paged_client(monkeypatch, [first, second])

        issues = await github.assigned_issues("LogosOSSAgent")

        assert len(issues) == 101
        assert [p["page"] for p in requested] == [1, 2]
        assert requested[0]["assignee"] == "LogosOSSAgent"

    async def test_pagination_stops_at_the_page_ceiling(self, monkeypatch):
        # A pathological thread must not turn one poll into hundreds of
        # requests — and the truncation is logged rather than silent.
        full_page = [{"id": i, "state": "COMMENTED", "submitted_at": "2020-01-01T00:00:00Z"} for i in range(100)]
        requested = self._paged_client(monkeypatch, [full_page] * (github._MAX_PAGES + 5))

        await github.latest_changes_requested_review(772)

        assert len(requested) == github._MAX_PAGES

    async def test_a_review_request_is_found_on_the_last_page(self, monkeypatch):
        # The same trap the review list has: the timeline answers
        # oldest-first, so on a busy pull request the request that was just
        # made sits on the last page, not the first.
        noise = [{"event": "commented", "actor": {"login": "a"}} for _ in range(100)]
        request = {
            "id": 412345678,
            "event": "review_requested",
            "requested_reviewer": {"login": "LogosOSSAgent"},
            "actor": {"login": "wasnertobias"},
        }
        self._paged_client(monkeypatch, [noise, [request]])

        assert await github.who_asked_for_a_review(772, "LogosOSSAgent") == ("wasnertobias", 412345678)

    async def test_a_review_request_lost_to_the_page_ceiling_is_not_answered(self, monkeypatch):
        # The timeline is oldest-first, so a truncated read holds the
        # *oldest* events. A matching actor in that remainder is an old
        # gesture, not the request that is on the table now — acting on it
        # would be a guess, so the question is refused instead.
        oldest = {
            "event": "review_requested",
            "requested_reviewer": {"login": "LogosOSSAgent"},
            "actor": {"login": "old-maintainer"},
        }
        full_page = [oldest] + [{"event": "commented", "actor": {"login": "a"}} for _ in range(99)]
        self._paged_client(monkeypatch, [full_page] * (github._MAX_PAGES + 5))

        assert await github.who_asked_for_a_review(772, "LogosOSSAgent") is None

    async def test_a_complete_timeline_without_a_request_names_nobody(self, monkeypatch):
        # A read that completed and names no requester is not the same
        # answer as a read that was cut off: the first is "nobody asked
        # that I can see", the second is "I cannot say", and the poller
        # logs the two differently.
        self._paged_client(
            monkeypatch,
            [
                [
                    {
                        "event": "review_requested",
                        "requested_reviewer": {"login": "someone-else"},
                        "actor": {"login": "a"},
                    }
                ]
            ],
        )

        assert await github.who_asked_for_a_review(772, "LogosOSSAgent") == ("", None)

    async def test_a_remade_review_request_answers_with_the_newest_event(self, monkeypatch):
        # Asking again — remove the reviewer, add them back — writes a new
        # event. "Who asked" is answered by the newest of them, and the
        # caller needs its identity to tell the two requests apart.
        self._paged_client(
            monkeypatch,
            [
                [
                    {
                        "id": 111,
                        "event": "review_requested",
                        "requested_reviewer": {"login": "LogosOSSAgent"},
                        "actor": {"login": "old-maintainer"},
                    },
                    {
                        "id": 222,
                        "event": "review_requested",
                        "requested_reviewer": {"login": "LogosOSSAgent"},
                        "actor": {"login": "wasnertobias"},
                    },
                ]
            ],
        )

        assert await github.who_asked_for_a_review(772, "LogosOSSAgent") == ("wasnertobias", 222)


class TestReactionsAndReplies:
    """Saying "seen" and saying the answer.

    Both are the runner's job: the agent phase holds no GitHub credential,
    so the acknowledgement and the reply are posted by the process that
    does.
    """

    @staticmethod
    def _capture(monkeypatch, status=201, payload=None):
        sent: list = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                sent.append({"url": url, "json": json})
                return FakeResponse(status, payload or {"html_url": "https://github.com/x/y#c1"})

        monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(github, "settings", replace(github.settings, github_token="tok"))
        return sent

    async def test_an_issue_is_acknowledged_with_eyes(self, monkeypatch):
        sent = self._capture(monkeypatch)

        assert await github.react("/repos/ls1intum/edutelligence/issues/812") is True

        assert sent[0]["url"].endswith("/issues/812/reactions")
        assert sent[0]["json"] == {"content": "eyes"}

    async def test_an_existing_reaction_counts_as_acknowledged(self, monkeypatch):
        # GitHub answers 200 when the reaction is already there; the point
        # is the state, not who created it.
        self._capture(monkeypatch, status=200)
        assert await github.react("/repos/ls1intum/edutelligence/issues/812") is True

    async def test_an_answer_goes_to_the_thread_it_was_asked_in(self, monkeypatch):
        sent = self._capture(monkeypatch)

        url = await github.post_issue_comment(772, "the answer")

        assert sent[0]["url"].endswith("/issues/772/comments")
        assert sent[0]["json"] == {"body": "the answer"}
        assert url.startswith("https://github.com/")

    async def test_an_inline_question_is_answered_inline(self, monkeypatch):
        # A line-specific question answered as a top-level comment would be
        # an answer nobody finds.
        sent = self._capture(monkeypatch)

        await github.reply_to_review_comment(772, 3910035243, "the answer")

        assert sent[0]["url"].endswith("/pulls/772/comments/3910035243/replies")
        assert sent[0]["json"] == {"body": "the answer"}


class TestReviewSupersession:
    """A reviewer who approves has withdrawn their earlier objection."""

    @staticmethod
    def _reviews(monkeypatch, reviews):
        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None, params=None):
                page = int((params or {}).get("page", 1))
                return FakeResponse(200, reviews if page == 1 else [])

        monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(github, "settings", replace(github.settings, github_token="tok"))

    async def test_an_approval_after_a_change_request_withdraws_it(self, monkeypatch):
        self._reviews(
            monkeypatch,
            [
                {"id": 1, "state": "CHANGES_REQUESTED", "submitted_at": "2026-09-01T10:00:00Z", "user": {"login": "a"}},
                {"id": 2, "state": "APPROVED", "submitted_at": "2026-09-02T10:00:00Z", "user": {"login": "a"}},
            ],
        )

        assert await github.latest_changes_requested_review(772) is None

    async def test_a_change_request_after_an_approval_is_work(self, monkeypatch):
        self._reviews(
            monkeypatch,
            [
                {"id": 1, "state": "APPROVED", "submitted_at": "2026-09-01T10:00:00Z", "user": {"login": "a"}},
                {"id": 2, "state": "CHANGES_REQUESTED", "submitted_at": "2026-09-02T10:00:00Z", "user": {"login": "a"}},
            ],
        )

        review = await github.latest_changes_requested_review(772)

        assert review["id"] == 2

    async def test_a_plain_comment_does_not_withdraw_a_change_request(self, monkeypatch):
        # A COMMENTED review states no position, so the reviewer's earlier
        # objection still stands.
        self._reviews(
            monkeypatch,
            [
                {"id": 1, "state": "CHANGES_REQUESTED", "submitted_at": "2026-09-01T10:00:00Z", "user": {"login": "a"}},
                {"id": 2, "state": "COMMENTED", "submitted_at": "2026-09-02T10:00:00Z", "user": {"login": "a"}},
            ],
        )

        review = await github.latest_changes_requested_review(772)
        assert review is not None and review["id"] == 1


class TestThreadIdentity:
    def test_a_reply_belongs_to_the_thread_it_answers(self):
        assert github.thread_root_of({"id": 5, "in_reply_to_id": 1}) == 1

    def test_a_thread_starter_is_its_own_root(self):
        assert github.thread_root_of({"id": 5}) == 5

    def test_a_comment_carries_its_time(self):
        moment = github.created_at_of({"created_at": "2026-09-02T10:00:00Z"})
        assert moment is not None and moment.year == 2026

    def test_a_comment_without_a_time_says_so(self):
        assert github.created_at_of({}) is None


class TestTheConversationHandedToASession:
    """What a takeover is told, and what it is told is missing.

    The task states that the conversation it carries is all of it, because
    the sandbox cannot fetch more. Anything left out therefore has to be
    named — a silent omission turns that sentence into a false one.
    """

    @staticmethod
    def install(monkeypatch, *, reviews=None, inline=None, discussion=None, truncated=()):
        async def _get_all_bounded(path, params=None):
            if path.endswith("/reviews"):
                if isinstance(reviews, Exception):
                    raise reviews
                return reviews or [], "reviews" in truncated
            if path.endswith("/pulls/772/comments"):
                return inline or [], "inline" in truncated
            return discussion or [], "discussion" in truncated

        monkeypatch.setattr(github, "_get_all_bounded", _get_all_bounded)

    @staticmethod
    def comment(index: int) -> dict:
        return {
            "user": {"login": "wasnertobias"},
            "body": f"point {index}",
            "created_at": f"2026-09-0{index % 9 + 1}T10:00:00Z",
        }

    async def test_a_complete_conversation_reports_nothing_missing(self, monkeypatch):
        self.install(monkeypatch, discussion=[self.comment(1), self.comment(2)])

        entries, missing = await github.pull_request_conversation(772)

        assert len(entries) == 2 and missing == []

    async def test_everything_read_is_returned_for_the_caller_to_cut(self, monkeypatch):
        # The cut belongs to the caller, after it has decided whose entries
        # count: a review that is fifteen comments long would otherwise
        # spend the whole allowance on entries about to be dropped, and the
        # unanswered early comment is exactly what falls off that end.
        self.install(monkeypatch, discussion=[self.comment(index) for index in range(10)])

        entries, missing = await github.pull_request_conversation(772)

        assert len(entries) == 10 and missing == []

    async def test_a_listing_that_hit_its_page_ceiling_is_named(self, monkeypatch):
        # Two thousand entries read out of more is incomplete context, and
        # the oldest part at that: what is gone is the part still open.
        self.install(monkeypatch, discussion=[self.comment(1)], truncated=("discussion",))

        _, missing = await github.pull_request_conversation(772)

        assert missing and "comments beyond the first" in missing[0]

    async def test_a_source_that_failed_is_named(self, monkeypatch):
        self.install(monkeypatch, reviews=RuntimeError("502"), discussion=[self.comment(1)])

        entries, missing = await github.pull_request_conversation(772)

        assert len(entries) == 1
        assert "reviews" in missing


class TestWatchingEveryCheck:
    """ "Did this change pass CI" is not a question about one workflow.

    The build workflow has its own waiter because a dev deploy needs that
    specific image. What an unattended agent actually breaks is the lint
    and test workflows — and watching only the build reported success on a
    commit whose linter was red.
    """

    @staticmethod
    def _answers(monkeypatch, pages):
        """Serve one check-runs payload per poll, repeating the last."""
        served = []

        async def fake_get(path, params=None, **kwargs):
            served.append(path)
            return pages[min(len(served) - 1, len(pages) - 1)]

        monkeypatch.setattr(github, "_get", fake_get)
        return served

    async def test_a_red_lint_run_is_a_failure_even_when_the_build_is_green(self, monkeypatch):
        self._answers(
            monkeypatch,
            [
                {
                    "check_runs": [
                        {"name": "Build", "status": "completed", "conclusion": "success"},
                        {
                            "name": "Logos Lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "html_url": "https://github.com/x/y/runs/1",
                        },
                    ]
                }
            ],
        )

        status, detail = await github.wait_for_checks("a" * 40)

        assert status == "failed"
        assert "Logos Lint" in detail

    async def test_everything_green_is_success(self, monkeypatch):
        self._answers(
            monkeypatch,
            [
                {
                    "check_runs": [
                        {"name": "Build", "status": "completed", "conclusion": "success"},
                        {"name": "Logos Test", "status": "completed", "conclusion": "skipped"},
                    ]
                }
            ],
        )

        status, _ = await github.wait_for_checks("a" * 40)

        assert status == "success"

    async def test_a_deployment_waiting_for_approval_is_not_a_failure(self, monkeypatch):
        # `action_required` is a human being asked to approve a deploy. An
        # agent cannot fix that, and queueing a session to try is worse
        # than doing nothing.
        self._answers(
            monkeypatch,
            [
                {
                    "check_runs": [
                        {"name": "Deploy", "status": "completed", "conclusion": "action_required"},
                        {"name": "Logos Test", "status": "completed", "conclusion": "success"},
                    ]
                }
            ],
        )

        status, _ = await github.wait_for_checks("a" * 40)

        assert status == "success"

    async def test_no_checks_yet_is_not_success(self, monkeypatch):
        # The seconds after a push: GitHub has not queued anything. Calling
        # that green would clear the follow-up before CI had an opinion.
        self._answers(monkeypatch, [{"check_runs": []}])

        status, detail = await github.wait_for_checks("a" * 40, timeout_s=0.02, poll_s=0.01)

        assert status == "timeout"
        assert "none reported yet" in detail

    async def test_checks_still_running_time_out_rather_than_fail(self, monkeypatch):
        self._answers(
            monkeypatch,
            [{"check_runs": [{"name": "Logos Test", "status": "in_progress", "conclusion": None}]}],
        )

        status, detail = await github.wait_for_checks("a" * 40, timeout_s=0.02, poll_s=0.01)

        assert status == "timeout"
        assert "Logos Test" in detail

    async def test_a_failing_check_ends_the_wait_before_the_others_finish(self, monkeypatch):
        served = self._answers(
            monkeypatch,
            [
                {
                    "check_runs": [
                        {"name": "Logos Lint", "status": "completed", "conclusion": "failure"},
                        {"name": "Build", "status": "in_progress", "conclusion": None},
                    ]
                }
            ],
        )

        status, _ = await github.wait_for_checks("a" * 40, timeout_s=5.0, poll_s=0.01)

        assert status == "failed"
        # One look: the rest of CI has nothing to add once there is
        # something to fix.
        assert len(served) == 1

    async def test_an_unreadable_answer_is_unknown_rather_than_red(self, monkeypatch):
        async def fake_get(path, params=None, **kwargs):
            raise github.GitHubError("500")

        monkeypatch.setattr(github, "_get", fake_get)

        status, _ = await github.wait_for_checks("a" * 40, timeout_s=0.02, poll_s=0.01)

        # A GitHub that blinked is not a failed build. Reporting one would
        # queue a session to fix a failure that never happened.
        assert status == "timeout"


class TestAskingWhoIsInATeam:
    """Who may direct a session, asked of the organisation rather than of
    the repository.

    A write collaborator is not the same thing as a member of the teams
    that own this runner, and the difference only holds if a non-member can
    be told apart from a question the token cannot ask: GitHub answers both
    with a 404.
    """

    @staticmethod
    def _github(monkeypatch, answers):
        """`answers` maps API path to a payload, an int status, or an error."""

        asked: list = []

        async def fake_get(path, params=None, **kwargs):
            asked.append(path)
            answer = answers.get(path, 404)
            if isinstance(answer, int):
                raise github.GitHubError(f"GET {path} failed ({answer})", status=answer)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(github, "_get", fake_get)
        monkeypatch.setattr(
            github,
            "settings",
            replace(github.settings, repo_slug="ls1intum/edutelligence", trusted_teams=("logos-developers",)),
        )
        return asked

    async def test_a_member_is_one(self, monkeypatch):
        self._github(
            monkeypatch,
            {"/orgs/ls1intum/teams/logos-developers/memberships/tobias": {"state": "active"}},
        )

        assert await github.in_a_trusted_team("tobias") is True

    async def test_a_non_member_of_a_visible_team_is_a_no(self, monkeypatch):
        # The 404 that used to be indistinguishable from "cannot ask", and
        # so let anybody with push access direct a session.
        asked = self._github(monkeypatch, {"/orgs/ls1intum/teams/logos-developers": {"slug": "logos-developers"}})

        assert await github.in_a_trusted_team("a-collaborator") is False
        assert "/orgs/ls1intum/teams/logos-developers" in asked

    async def test_a_token_that_cannot_see_the_team_leaves_it_unanswered(self, monkeypatch):
        # No `read:org`: every team is a 404, and answering "no" would
        # silence the whole repository the first time a token was reissued
        # without the scope.
        self._github(monkeypatch, {})

        assert await github.in_a_trusted_team("tobias") is None

    async def test_a_refused_request_is_unanswered_too(self, monkeypatch):
        self._github(monkeypatch, {"/orgs/ls1intum/teams/logos-developers/memberships/tobias": 403})

        assert await github.in_a_trusted_team("tobias") is None

    async def test_a_pending_invitation_is_not_membership(self, monkeypatch):
        self._github(
            monkeypatch,
            {"/orgs/ls1intum/teams/logos-developers/memberships/invited": {"state": "pending"}},
        )

        assert await github.in_a_trusted_team("invited") is False

    async def test_no_configured_teams_is_not_a_refusal(self, monkeypatch):
        monkeypatch.setattr(github, "settings", replace(github.settings, trusted_teams=()))

        assert await github.in_a_trusted_team("tobias") is None


class FakeGraphQLResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def fake_graphql_client(monkeypatch, calls, answers):
    """Point the GraphQL endpoint at a stub.

    ``answers`` is a list of (status_code, payload) pairs, one per call;
    when the calls outlast the script, the last answer repeats.
    """

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append({"method": "POST", "url": url, "json": json})
            status, payload = answers[min(len(calls) - 1, len(answers) - 1)]
            return FakeGraphQLResponse(status, payload)

    monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(github, "settings", replace(github.settings, github_token="tok", github_login="logos"))


def _thread_payload(thread_id: str, comment_id: int, resolved: bool = False) -> dict:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "comments": {"nodes": [{"databaseId": comment_id}]},
    }


def _threads_payload(nodes, has_next: bool = False, end_cursor: str = "cursor-1") -> dict:
    return {
        "repository": {
            "pullRequest": {
                "reviewThreads": {
                    "nodes": nodes,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                }
            }
        }
    }


def _thread_comments_payload(
    bodies, has_next: bool = False, end_cursor: str = "cursor-1", author: str | None = "logos"
) -> dict:
    nodes = []
    for body in bodies:
        node = {"body": body}
        if author is not None:
            node["author"] = {"login": author}
        nodes.append(node)
    return {
        "node": {
            "comments": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
            }
        }
    }


class TestReviewRepliesAndReRequests:
    """What the runner posts after a review session: one answer per thread,
    the threads resolved, and the reviewer asked to look again."""

    async def test_a_single_review_is_read_by_its_id(self, monkeypatch):
        asked: list = []

        async def fake_get(path, params=None, **kwargs):
            asked.append(path)
            return {"id": 42, "user": {"login": "claudia"}, "state": "CHANGES_REQUESTED"}

        monkeypatch.setattr(github, "_get", fake_get)

        review = await github.review(772, 42)
        assert asked == ["/repos/ls1intum/edutelligence/pulls/772/reviews/42"]
        assert review["user"]["login"] == "claudia"

    async def test_the_review_request_posts_the_named_reviewers(self, monkeypatch):
        calls: list = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                calls.append({"url": url, "json": json})
                return FakeGraphQLResponse(200)

        monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(github, "settings", replace(github.settings, github_token="tok"))

        await github.request_pull_review(772, ["claudia"])

        assert calls == [
            {
                "url": "https://api.github.com/repos/ls1intum/edutelligence/pulls/772/requested_reviewers",
                "json": {"reviewers": ["claudia"]},
            }
        ]

    async def test_an_empty_review_request_posts_nothing(self, monkeypatch):
        calls: list = []
        fake_graphql_client(monkeypatch, calls, [(200, {})])

        await github.request_pull_review(772, [])

        assert calls == []

    async def test_the_thread_map_keys_threads_by_their_first_comment(self, monkeypatch):
        calls: list = []
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (
                    200,
                    {
                        "data": _threads_payload(
                            [_thread_payload("PRRT_1", 101), _thread_payload("PRRT_2", 102, resolved=True)]
                        )
                    },
                )
            ],
        )

        mapped = await github.review_thread_map(772)

        assert mapped == {
            101: {"thread": "PRRT_1", "resolved": False},
            102: {"thread": "PRRT_2", "resolved": True},
        }
        assert calls[0]["url"] == "https://api.github.com/graphql"
        assert calls[0]["json"]["variables"] == {
            "owner": "ls1intum",
            "name": "edutelligence",
            "number": 772,
            "after": None,
        }

    async def test_the_thread_map_follows_the_next_page(self, monkeypatch):
        calls: list = []
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, {"data": _threads_payload([_thread_payload("PRRT_1", 101)], has_next=True)}),
                (200, {"data": _threads_payload([_thread_payload("PRRT_2", 102)], has_next=False)}),
            ],
        )

        mapped = await github.review_thread_map(772)

        assert set(mapped) == {101, 102}
        assert calls[1]["json"]["variables"]["after"] == "cursor-1"

    async def test_a_thread_without_a_comment_is_not_mapped(self, monkeypatch):
        calls: list = []
        fake_graphql_client(
            monkeypatch,
            calls,
            [(200, {"data": _threads_payload([{"id": "PRRT_1", "isResolved": False, "comments": {"nodes": []}}])})],
        )

        assert await github.review_thread_map(772) == {}

    async def test_a_posted_reply_is_found_in_its_thread(self, monkeypatch):
        # The marker lives in the reply's body: the thread map names the
        # thread the comment starts, and that thread's comments are asked
        # for the marker.
        calls: list = []
        marker = "<!-- logos reply 31 101 -->"
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101), _thread_payload("PRRT_2", 102)])}
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, map_answer),
                (200, {"data": _thread_comments_payload(["the question", f"the answer\n\n{marker}"])}),
                (200, map_answer),
                (200, {"data": _thread_comments_payload(["another question", "an answer to something else"])}),
            ],
        )

        assert await github.review_reply_is_in_thread(772, 101, marker) is True
        assert await github.review_reply_is_in_thread(772, 102, "<!-- logos reply 31 102 -->") is False
        assert calls[1]["json"]["variables"]["threadId"] == "PRRT_1"
        assert calls[3]["json"]["variables"]["threadId"] == "PRRT_2"

    async def test_the_reply_look_follows_the_next_page(self, monkeypatch):
        # The reply sits past the thread's first page of comments: the
        # look-up keeps paging the thread until it is found.
        calls: list = []
        marker = "<!-- logos reply 31 102 -->"
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101), _thread_payload("PRRT_2", 102)])}
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, map_answer),
                (200, {"data": _thread_comments_payload(["first page", "no marker here"], has_next=True)}),
                (200, {"data": _thread_comments_payload([f"and the answer\n\n{marker}"])}),
            ],
        )

        assert await github.review_reply_is_in_thread(772, 102, marker) is True
        assert calls[1]["json"]["variables"]["threadId"] == "PRRT_2"
        assert calls[2]["json"]["variables"]["after"] == "cursor-1"

    async def test_a_reply_beyond_the_first_hundred_comments_is_found(self, monkeypatch):
        # The shape that would have been missed: a thread with more
        # comments than one page holds, and the marker past the first one.
        # A look-up that stopped at page one would have posted the answer
        # twice.
        calls: list = []
        marker = "<!-- logos reply 31 101 -->"
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101)])}
        first_page = [f"comment {i}" for i in range(100)]
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, map_answer),
                (200, {"data": _thread_comments_payload(first_page, has_next=True)}),
                (200, {"data": _thread_comments_payload([f"the answer\n\n{marker}"])}),
            ],
        )

        assert await github.review_reply_is_in_thread(772, 101, marker) is True

    async def test_a_comment_without_its_own_thread_is_not_lookable(self, monkeypatch):
        # A comment that is a reply inside somebody else's thread starts no
        # thread of its own, and the map does not name that thread: the
        # look-up gives up after the map, and the POST goes ahead as before.
        calls: list = []
        fake_graphql_client(monkeypatch, calls, [(200, {"data": _threads_payload([])})])

        assert await github.review_reply_is_in_thread(772, 999, "<!-- logos reply 31 999 -->") is False
        assert len(calls) == 1

    async def test_a_thread_map_at_the_page_ceiling_is_an_error(self, monkeypatch):
        # A pull request with more threads than the ceiling maps is not
        # mapped partially: the map's caller would claim a delivery
        # complete while a thread is left unresolved, and the retry is the
        # only safe outcome.
        calls: list = []

        async def endless(_query, variables):
            calls.append(variables)
            return {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [_thread_payload("PRRT_1", 101)],
                            "pageInfo": {"hasNextPage": True, "endCursor": f"cursor-{len(calls)}"},
                        }
                    }
                }
            }

        monkeypatch.setattr(github, "_graphql", endless)

        with pytest.raises(github.GitHubError):
            await github.review_thread_map(772)
        assert len(calls) == github._MAX_PAGES

    async def test_a_thread_at_the_comment_ceiling_is_an_error(self, monkeypatch):
        # More comments in one thread than the ceiling pages: the look-up
        # cannot rule the marker out, and ruling it out is what the POST
        # depends on.
        calls: list = []
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101)])}
        never_done = {"data": _thread_comments_payload(["no marker"], has_next=True)}
        fake_graphql_client(monkeypatch, calls, [(200, map_answer), (200, never_done)])

        with pytest.raises(github.GitHubError):
            await github.review_reply_is_in_thread(772, 101, "<!-- logos reply 31 101 -->")

    async def test_a_posted_answer_is_found_on_the_pull_request(self, monkeypatch):
        # The single answer's mark is looked up across the pull request's
        # comments; a hit anywhere in them is a hit.
        asked: list = []

        async def fake_get(path, params=None, **kwargs):
            asked.append(path)
            return [
                {"body": "an earlier discussion"},
                {"body": "the answer\n\n<!-- logos answer 31 -->", "user": {"login": "LogosOSSAgent"}},
            ]

        monkeypatch.setattr(github, "_get", fake_get)

        assert await github.issue_comment_contains(772, "<!-- logos answer 31 -->") is True
        assert await github.issue_comment_contains(772, "<!-- logos answer 32 -->") is False
        assert len(asked) == 2
        assert asked[0].endswith("/issues/772/comments")

    async def test_a_participant_authored_marker_is_not_delivery(self, monkeypatch):
        # A posted marker carries the session id, which a participant of
        # the pull request can read. Writing the expected marker
        # themselves would suppress the answer that is still owed, so a
        # marker counts only when the account it was posted by is the
        # account the runner posts with.
        asked: list = []

        async def fake_get(path, params=None, **kwargs):
            asked.append(path)
            return [{"body": "<!-- logos answer 31 -->", "user": {"login": "a-participant"}}]

        monkeypatch.setattr(github, "_get", fake_get)

        assert await github.issue_comment_contains(772, "<!-- logos answer 31 -->") is False

    async def test_a_participant_authored_thread_marker_is_not_delivery(self, monkeypatch):
        # The same binding inside a review thread: a marker posted by
        # somebody else does not stand for the runner's reply, and the
        # look-up still reads the thread to the end before ruling it out.
        calls: list = []
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101)])}
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, map_answer),
                (200, {"data": _thread_comments_payload(["<!-- logos reply 31 101 -->"], author="a-participant")}),
            ],
        )

        assert await github.review_reply_is_in_thread(772, 101, "<!-- logos reply 31 101 -->") is False

    async def test_the_thread_marker_matches_the_verified_spelling(self, monkeypatch):
        # The configured identity may carry any casing, but the marker is
        # recognized by the exact spelling the API verified the account
        # under — the same spelling it hands back on the comment's author.
        # The fake's configured login is the differently cased "logos".
        calls: list = []
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101)])}
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, map_answer),
                (
                    200,
                    {"data": _thread_comments_payload(["the answer\n\n<!-- logos reply 31 101 -->"], author="Logos")},
                ),
            ],
        )
        monkeypatch.setattr(github, "_verified_login", "Logos")

        assert await github.review_reply_is_in_thread(772, 101, "<!-- logos reply 31 101 -->") is True

    async def test_the_issue_marker_matches_the_verified_spelling(self, monkeypatch):
        # The same rule on the REST look-up: the configured login is
        # spelled in any casing, and the marker is recognized by the exact
        # spelling the API verified the account under.
        asked: list = []
        monkeypatch.setattr(github, "settings", replace(github.settings, github_login="logosossagent"))
        monkeypatch.setattr(github, "_verified_login", "LogosOSSAgent")

        async def fake_get(path, params=None, **kwargs):
            asked.append(path)
            return [{"body": "<!-- logos answer 31 -->", "user": {"login": "LogosOSSAgent"}}]

        monkeypatch.setattr(github, "_get", fake_get)

        assert await github.issue_comment_contains(772, "<!-- logos answer 31 -->") is True

    async def test_a_differently_cased_thread_login_is_not_the_verified_account(self, monkeypatch):
        # The comparison is exact, not case-insensitive: a login that
        # merely spells alike apart from case is not the account the
        # token was verified as, and its marker must not make the retry
        # skip an answer the session still owes.
        calls: list = []
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101)])}
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, map_answer),
                (200, {"data": _thread_comments_payload(["<!-- logos reply 31 101 -->"], author="LOGOS")}),
            ],
        )
        monkeypatch.setattr(github, "_verified_login", "logos")

        assert await github.review_reply_is_in_thread(772, 101, "<!-- logos reply 31 101 -->") is False

    async def test_a_differently_cased_issue_login_is_not_the_verified_account(self, monkeypatch):
        # The same exactness on the REST look-up.
        asked: list = []
        monkeypatch.setattr(github, "_verified_login", "LogosOSSAgent")

        async def fake_get(path, params=None, **kwargs):
            asked.append(path)
            return [{"body": "<!-- logos answer 31 -->", "user": {"login": "logosossagent"}}]

        monkeypatch.setattr(github, "_get", fake_get)

        assert await github.issue_comment_contains(772, "<!-- logos answer 31 -->") is False

    async def test_the_map_reads_out_a_thread_beyond_its_first_page(self, monkeypatch):
        # A thread that holds more comments than its first page: the rest
        # is read out of the thread, so a target after comment 100 still
        # maps to its thread.
        calls: list = []
        first_page = {
            "id": "PRRT_1",
            "isResolved": False,
            "comments": {
                "nodes": [{"databaseId": i} for i in range(1, 101)],
                "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
            },
        }
        rest = {
            "data": {
                "node": {
                    "comments": {
                        "nodes": [{"databaseId": 101}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
        fake_graphql_client(monkeypatch, calls, [(200, {"data": _threads_payload([first_page])}), (200, rest)])

        mapped = await github.review_thread_map(772)

        assert mapped[101] == {"thread": "PRRT_1", "resolved": False}
        assert calls[1]["json"]["variables"]["threadId"] == "PRRT_1"
        assert calls[1]["json"]["variables"]["after"] == "c1"

    async def test_the_map_refuses_a_thread_it_cannot_finish(self, monkeypatch):
        # A thread with more comment pages than the ceiling: the map
        # cannot be completed, and a partial map would silently drop a
        # target — so it raises.
        calls: list = []

        async def fetch(_query, variables):
            calls.append(variables)
            if "threadId" in variables:
                n = sum(1 for v in calls if "threadId" in v)
                return {
                    "node": {
                        "comments": {
                            "nodes": [{"databaseId": 100 + n}],
                            "pageInfo": {"hasNextPage": True, "endCursor": f"c{n}"},
                        }
                    }
                }
            return {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "id": "PRRT_1",
                                    "isResolved": False,
                                    "comments": {
                                        "nodes": [{"databaseId": i} for i in range(1, 101)],
                                        "pageInfo": {"hasNextPage": True, "endCursor": "c0"},
                                    },
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }

        monkeypatch.setattr(github, "_graphql", fetch)

        with pytest.raises(github.GitHubError):
            await github.review_thread_map(772)
        assert len(calls) == 1 + github._MAX_PAGES

    async def test_the_map_covers_the_replies_inside_a_thread(self, monkeypatch):
        # A comment that is a reply inside somebody else's thread still
        # maps to that thread: the answer to it is named after the
        # comment, and reconciliation and resolution both look it up.
        calls: list = []
        payload = {
            "data": _threads_payload(
                [
                    {
                        "id": "PRRT_1",
                        "isResolved": False,
                        "comments": {"nodes": [{"databaseId": 101}, {"databaseId": 500}]},
                    }
                ]
            )
        }
        fake_graphql_client(monkeypatch, calls, [(200, payload)])

        mapped = await github.review_thread_map(772)

        assert set(mapped) == {101, 500}
        assert mapped[500] == {"thread": "PRRT_1", "resolved": False}

    async def test_a_reply_inside_another_thread_is_found_there(self, monkeypatch):
        # The marker look-up follows the same map: a comment that replies
        # inside somebody else's thread is reconciled against that thread,
        # not ruled out because it starts none of its own.
        calls: list = []
        marker = "<!-- logos reply 31 500 -->"
        map_answer = {
            "data": _threads_payload(
                [
                    {
                        "id": "PRRT_1",
                        "isResolved": False,
                        "comments": {"nodes": [{"databaseId": 101}, {"databaseId": 500}]},
                    }
                ]
            )
        }
        fake_graphql_client(
            monkeypatch,
            calls,
            [(200, map_answer), (200, {"data": _thread_comments_payload([f"the answer\n\n{marker}"])})],
        )

        assert await github.review_reply_is_in_thread(772, 500, marker) is True
        assert calls[1]["json"]["variables"]["threadId"] == "PRRT_1"

    async def test_a_passed_map_is_not_fetched_again(self, monkeypatch):
        # The delivery builds the map once and hands it in: the look-up
        # asks the thread for the marker and goes back for nothing else.
        calls: list = []
        marker = "<!-- logos reply 31 101 -->"
        fake_graphql_client(
            monkeypatch,
            calls,
            [(200, {"data": _thread_comments_payload([f"the answer\n\n{marker}"])})],
        )
        threads = {101: {"thread": "PRRT_1", "resolved": False}}

        assert await github.review_reply_is_in_thread(772, 101, marker, threads) is True
        assert len(calls) == 1
        assert calls[0]["json"]["variables"]["threadId"] == "PRRT_1"

    async def test_a_stuck_thread_map_cursor_is_an_error(self, monkeypatch):
        # A page that claims there is more and hands back the cursor it was
        # asked with is not a page: following it would read the same page
        # until the ceiling, spending the rate budget on nothing.
        calls: list = []
        page = {"data": _threads_payload([_thread_payload("PRRT_1", 101)], has_next=True, end_cursor="same")}
        fake_graphql_client(monkeypatch, calls, [(200, page)])

        with pytest.raises(github.GitHubError):
            await github.review_thread_map(772)
        assert len(calls) == 2

    async def test_a_stuck_thread_comments_cursor_is_an_error(self, monkeypatch):
        calls: list = []
        map_answer = {"data": _threads_payload([_thread_payload("PRRT_1", 101)])}
        stuck = {"data": _thread_comments_payload(["no marker"], has_next=True, end_cursor="same")}
        fake_graphql_client(monkeypatch, calls, [(200, map_answer), (200, stuck)])

        with pytest.raises(github.GitHubError):
            await github.review_reply_is_in_thread(772, 101, "<!-- logos reply 31 101 -->")
        assert len(calls) == 3

    async def test_an_incomplete_comment_listing_is_an_error(self, monkeypatch):
        # A listing that hits the page ceiling cannot rule the marker out,
        # and ruling it out is what the POST depends on.
        asked: list = []

        async def full_page(_path, params=None, **kwargs):
            asked.append(params)
            return [{"body": f"comment {i}"} for i in range(github._PAGE_SIZE)]

        monkeypatch.setattr(github, "_get", full_page)

        with pytest.raises(github.GitHubError):
            await github.issue_comment_contains(772, "<!-- logos answer 31 -->")
        assert len(asked) == github._MAX_PAGES

    async def test_resolving_threads_runs_one_mutation_per_thread(self, monkeypatch):
        # The exact request, pinned to the schema: the mutation takes the id
        # wrapped in `input` and answers with the thread it resolved. Any
        # other shape is a validation error GitHub refuses before doing
        # anything — which is what a first draft of this was.
        calls: list = []
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, {"data": {"resolveReviewThread": {"thread": {"id": "PRRT_1"}}}}),
                (200, {"data": {"resolveReviewThread": {"thread": {"id": "PRRT_2"}}}}),
            ],
        )

        await github.resolve_review_threads(["PRRT_1", "PRRT_2"])

        assert len(calls) == 2
        for call, thread_id in zip(calls, ("PRRT_1", "PRRT_2")):
            assert call["json"] == {
                "query": (
                    "mutation ResolveReviewThread($threadId: ID!) "
                    "{ resolveReviewThread(input: {threadId: $threadId}) { thread { id } } }"
                ),
                "variables": {"threadId": thread_id},
            }

    async def test_a_declined_resolution_does_not_stop_the_rest(self, monkeypatch):
        # GitHub answers a null when it will not resolve what it was given;
        # the other threads still get their call.
        calls: list = []
        fake_graphql_client(
            monkeypatch,
            calls,
            [
                (200, {"data": {"resolveReviewThread": None}}),
                (200, {"data": {"resolveReviewThread": {"threadId": "PRRT_2"}}}),
            ],
        )

        await github.resolve_review_threads(["PRRT_1", "PRRT_2"])

        assert len(calls) == 2

    async def test_a_graphql_error_is_an_error(self, monkeypatch):
        fake_graphql_client(monkeypatch, [], [(200, {"errors": [{"message": "forbidden", "type": "FORBIDDEN"}]})])

        with pytest.raises(github.GitHubError) as excinfo:
            await github.resolve_review_threads(["PRRT_1"])

        # The type is what separates a refusal a retry cannot fix from one
        # that can, so it has to reach the caller.
        assert excinfo.value.graphql_type == "FORBIDDEN"
        assert excinfo.value.status is None

    async def test_a_graphql_http_error_is_an_error(self, monkeypatch):
        fake_graphql_client(monkeypatch, [], [(403, None)])

        with pytest.raises(github.GitHubError):
            await github.review_thread_map(772)
