"""The runner's own GitHub calls: dispatch target, image tag, run selection.

These functions build small, fixed HTTP calls; the tests pin the URLs, the
dispatch inputs, and which workflow run counts as "the" build so a refactor
cannot quietly turn the dev deploy into a dispatch of the wrong workflow or
the wrong image tag.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from app import github


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

    async def test_reviews_are_read_past_the_first_page(self, monkeypatch):
        old = [{"id": i, "state": "COMMENTED", "submitted_at": "2020-01-01T00:00:00Z"} for i in range(100)]
        newest = {"id": 999, "state": "CHANGES_REQUESTED", "submitted_at": "2026-09-02T10:00:00Z"}
        requested = self._paged_client(monkeypatch, [old, [newest]])

        fresh = await github.reviews_since(772, datetime(2026, 9, 1, tzinfo=timezone.utc))

        assert [r["id"] for r in fresh] == [999]
        assert [p["page"] for p in requested] == [1, 2]
        assert all(p["per_page"] == 100 for p in requested)

    async def test_a_short_thread_costs_one_request(self, monkeypatch):
        requested = self._paged_client(
            monkeypatch, [[{"id": 1, "state": "APPROVED", "submitted_at": "2026-09-02T10:00:00Z"}]]
        )

        await github.reviews_since(772, datetime(2026, 9, 1, tzinfo=timezone.utc))

        assert len(requested) == 1

    async def test_labelled_issues_are_paginated_too(self, monkeypatch):
        first = [{"number": i, "title": "t"} for i in range(100)]
        second = [{"number": 500, "title": "the newest"}]
        requested = self._paged_client(monkeypatch, [first, second])

        issues = await github.labelled_issues("logos-agent", since=datetime(2026, 9, 1, tzinfo=timezone.utc))

        assert len(issues) == 101
        assert [p["page"] for p in requested] == [1, 2]

    async def test_pagination_stops_at_the_page_ceiling(self, monkeypatch):
        # A pathological thread must not turn one poll into hundreds of
        # requests — and the truncation is logged rather than silent.
        full_page = [{"id": i, "state": "COMMENTED", "submitted_at": "2020-01-01T00:00:00Z"} for i in range(100)]
        requested = self._paged_client(monkeypatch, [full_page] * (github._MAX_PAGES + 5))

        await github.reviews_since(772, datetime(2026, 9, 1, tzinfo=timezone.utc))

        assert len(requested) == github._MAX_PAGES
