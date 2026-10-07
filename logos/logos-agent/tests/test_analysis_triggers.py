"""Nightly re-analysis of linked team repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app import analysis_triggers, github
from app.analysis_triggers import ANALYSIS_TASK, UNCHANGED_CHECK, AnalysisPoller

HEAD = "a" * 40
MOVED = "b" * 40


def _link(link_id: int, last_commit: str | None) -> dict:
    return {
        "id": link_id,
        "team_id": 5,
        "repo_url": f"https://github.com/acme/r{link_id}.git",
        "repo_slug": f"acme/r{link_id}",
        "branch": "main",
        "paths": None,
        "last_commit": last_commit,
    }


def _poller(monkeypatch, links: list[dict], heads: dict[str, str | None]) -> tuple[AnalysisPoller, list]:
    poller = AnalysisPoller()
    queued: list[tuple[str, str | None]] = []

    async def links_for_nightly():
        return links

    async def queue(link, *, previous_commit=None):
        queued.append((link["repo_slug"], previous_commit))
        return 1000 + int(link["id"])

    async def branch_head(slug, branch):
        return heads.get(slug)

    monkeypatch.setattr(poller, "_links_for_nightly", links_for_nightly)
    monkeypatch.setattr(poller, "_queue", queue)
    monkeypatch.setattr(github, "branch_head", branch_head)
    return poller, queued


async def test_nightly_skips_unchanged_and_queues_moved_heads(monkeypatch):
    poller, queued = _poller(
        monkeypatch,
        [_link(1, HEAD), _link(2, HEAD), _link(3, HEAD)],
        {"acme/r1": HEAD, "acme/r2": MOVED, "acme/r3": None},
    )
    sessions = await poller._nightly_pass()
    # r1 unchanged: nothing starts. r2 moved: a normal analysis. r3 unknown
    # (private): queued with the previous commit so the session stops itself.
    assert queued == [("acme/r2", None), ("acme/r3", HEAD)]
    assert sessions == [1002, 1003]
    assert poller.status()["skipped_unchanged_total"] == 1


def test_nightly_runs_once_in_its_hour(monkeypatch):
    monkeypatch.setattr(analysis_triggers, "settings", replace(analysis_triggers.settings, analysis_nightly_hour_utc=1))
    poller = AnalysisPoller()
    night = datetime(2026, 10, 3, 1, 5, tzinfo=timezone.utc)
    assert poller._nightly_due(night)
    poller._nightly_done_for = night.date()
    assert not poller._nightly_due(night.replace(minute=50))
    assert not poller._nightly_due(datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc))
    assert poller._nightly_due(datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc))


def test_nightly_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(
        analysis_triggers, "settings", replace(analysis_triggers.settings, analysis_nightly_hour_utc=-1)
    )
    assert not AnalysisPoller()._nightly_due(datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc))


def test_unchanged_check_formats_into_the_task():
    task = ANALYSIS_TASK.format(repo_slug="acme/r", repo_url="u", paths="x") + UNCHANGED_CHECK.format(
        previous_commit=HEAD
    )
    assert f'{{"unchanged": true, "commit_sha": "{HEAD}"}}' in task
    assert "git rev-parse HEAD" in task


class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def _fake_client(response: _FakeResponse, calls: list):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers=None):
            calls.append((url, headers))
            return response

    return Client


async def test_branch_head_reads_the_sha_and_says_none_when_github_will_not(monkeypatch):
    calls: list = []
    monkeypatch.setattr(github.httpx, "AsyncClient", _fake_client(_FakeResponse(200, HEAD + "\n"), calls))
    assert await github.branch_head("acme/r", "feature/x") == HEAD
    assert calls[0][0].endswith("/repos/acme/r/commits/feature%2Fx")
    assert calls[0][1]["Accept"] == "application/vnd.github.sha"

    monkeypatch.setattr(github.httpx, "AsyncClient", _fake_client(_FakeResponse(404, "Not Found"), []))
    assert await github.branch_head("acme/private", "main") is None


async def test_a_lost_race_for_the_in_flight_slot_queues_no_session(monkeypatch):
    poller = AnalysisPoller()
    created: list = []

    async def claim(team_id, link_id):
        return None  # another writer holds the repository's in-flight slot

    async def create_session(**kwargs):
        created.append(kwargs)
        return 1

    monkeypatch.setattr(poller, "_insert_queued_analysis", claim)
    monkeypatch.setattr(analysis_triggers.db, "create_session", create_session)
    assert await poller._queue(_link(1, HEAD)) is None
    assert created == []


async def test_a_session_that_cannot_be_created_releases_the_slot(monkeypatch):
    poller = AnalysisPoller()
    dropped: list[int] = []

    async def claim(team_id, link_id):
        return 77

    async def workspace(team_id, link_id, branch):
        return 5

    async def create_session(**kwargs):
        raise ValueError("workspace busy")

    async def drop(analysis_id):
        dropped.append(analysis_id)

    monkeypatch.setattr(poller, "_insert_queued_analysis", claim)
    monkeypatch.setattr(poller, "_ensure_workspace", workspace)
    monkeypatch.setattr(poller, "_drop_queued_analysis", drop)
    monkeypatch.setattr(analysis_triggers.db, "create_session", create_session)
    assert await poller._queue(_link(1, HEAD)) is None
    assert dropped == [77]


async def test_a_failed_nightly_pass_is_retried_within_the_hour(monkeypatch):
    monkeypatch.setattr(analysis_triggers, "settings", replace(analysis_triggers.settings, analysis_nightly_hour_utc=1))
    poller = AnalysisPoller()

    async def nothing(*args, **kwargs):
        return []

    async def boom():
        raise RuntimeError("db down")

    class _Control:
        def admission_block(self):
            return ""

    async def current():
        return _Control()

    monkeypatch.setattr(poller, "_reconcile_stale_analyses", nothing)
    monkeypatch.setattr(poller, "_links_needing_analysis", nothing)
    monkeypatch.setattr(poller, "_nightly_pass", boom)
    monkeypatch.setattr(analysis_triggers.controls, "current", current)
    monkeypatch.setattr(analysis_triggers.model_policy, "current", lambda: type("P", (), {"ok": True, "detail": ""})())

    night = datetime(2026, 10, 3, 1, 5, tzinfo=timezone.utc)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return night

    monkeypatch.setattr(analysis_triggers, "datetime", _Clock)
    try:
        await poller.poll_once()
    except RuntimeError:
        pass
    assert poller._nightly_due(night.replace(minute=10))
