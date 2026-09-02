"""The GitHub calls this service makes on its own behalf.

Deliberately narrow. Session containers talk to GitHub themselves for the work
that needs a working copy (push, open a pull request), but anything that can
affect a deployed environment is dispatched from here, with a token the
container never sees. That is the whole reason this module exists rather than
letting the agent run `gh workflow run`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_API = "https://api.github.com"

# Workflows this service is willing to dispatch. Anything else is refused even
# if it is configured, so a mistyped or edited environment variable cannot turn
# the agent runner into a production deploy button.
_ALLOWED_WORKFLOWS = frozenset({"logos_deploy-dev.yml"})

# The ref the deploy workflow always runs on. It checks out the repository to
# copy docker-compose.yaml to the dev host, so that checkout must never come
# from a session branch — branch files are agent-editable, and a compose
# change there would execute on the dev host, outside the container sandbox.
# The session's code still reaches dev, but only as the prebuilt image tag.
_DEPLOY_REF = "main"


class GitHubError(RuntimeError):
    pass


class IdentityError(RuntimeError):
    """A configured token does not belong to the agent's GitHub account."""


async def token_login(token: str, *, timeout_s: float = 15.0) -> str:
    """The account a token authenticates as.

    Raises :class:`GitHubError` when the token cannot be resolved at all —
    unreachable API, revoked token — which callers treat differently from a
    token that resolves to the wrong account.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(
                f"{_API}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except Exception as exc:
        raise GitHubError(f"could not reach the GitHub API: {exc}") from exc
    if response.status_code != 200:
        raise GitHubError(f"token lookup failed ({response.status_code}): {response.text[:200]}")
    login = response.json().get("login")
    if not isinstance(login, str) or not login:
        raise GitHubError("the GitHub API returned no login for this token")
    return login


async def verify_identities() -> list[str]:
    """Check every configured token belongs to the agent account.

    Returns the notes worth logging (which token resolved to what, or why a
    check could not be made). Raises :class:`IdentityError` when a token
    resolves to a *different* account: that is a misconfiguration which would
    otherwise put agent commits, pull requests, and deploy dispatches under
    somebody else's name, and it must stop the service rather than be
    discovered afterwards in the repository's history.

    An unreachable API is not a mismatch and does not stop anything: the
    finalizer verifies the same thing inside the container before it pushes,
    so a network blip at startup cannot smuggle work out under a wrong
    identity.
    """
    expected = settings.github_login.strip().lower()
    notes: list[str] = []
    for label, token in (
        ("LOGOS_AGENT_GITHUB_TOKEN", settings.github_token),
        ("LOGOS_AGENT_SESSION_GITHUB_TOKEN", settings.session_github_token),
    ):
        if not token:
            notes.append(f"{label} is not configured")
            continue
        try:
            login = await token_login(token)
        except GitHubError as exc:
            notes.append(f"{label} could not be verified: {exc}")
            continue
        if login.strip().lower() != expected:
            raise IdentityError(
                f"{label} authenticates as '{login}', not as the configured agent "
                f"account '{settings.github_login}'. Agent work must run under that "
                f"account only — issue the token from it, or set "
                f"LOGOS_AGENT_GITHUB_LOGIN to the account it belongs to."
            )
        notes.append(f"{label} authenticates as {login}")
    return notes


def _headers() -> dict[str, str]:
    if not settings.github_token:
        raise GitHubError("LOGOS_AGENT_GITHUB_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def dispatch_dev_deploy(*, image_tag: str) -> str:
    """Trigger the dev deployment workflow and return a link to the run.

    Refuses any workflow other than the dev one. The dev deploy workflow is
    itself pinned to the dev environment and dispatched on the fixed trusted
    ref :data:`_DEPLOY_REF` — never on a session branch, since the workflow
    checks out the repository to copy ``docker-compose.yaml`` to the dev
    host, and a branch ref would let session edits run there. The only
    branch-derived value the workflow receives is the prebuilt image tag.
    """
    workflow = settings.deploy_workflow
    if workflow not in _ALLOWED_WORKFLOWS:
        raise GitHubError(
            f"workflow '{workflow}' is not an allowed deploy target " f"(allowed: {sorted(_ALLOWED_WORKFLOWS)})"
        )

    url = f"{_API}/repos/{settings.repo_slug}/actions/workflows/{workflow}/dispatches"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers=_headers(),
            json={"ref": _DEPLOY_REF, "inputs": {"image-tag": image_tag}},
        )
    if response.status_code not in (201, 204):
        raise GitHubError(f"workflow dispatch failed ({response.status_code}): {response.text}")

    return f"https://github.com/{settings.repo_slug}/actions/workflows/{workflow}"


async def latest_dev_deploy_run_id() -> int | None:
    """The id of the newest run of the deploy workflow on the trusted ref.

    Callers record this immediately before a dispatch — the pre-dispatch
    marker. GitHub run ids only increase, so the run the dispatch creates
    is the one that turns out newer than the marker, while a deploy that
    completed before it (or one another session dispatched) stays older and
    can no longer be mistaken for the dispatch's own run. Returns ``None``
    when the workflow has no run on the trusted ref yet.
    """
    url = f"{_API}/repos/{settings.repo_slug}/actions/workflows/{settings.deploy_workflow}/runs"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_headers(), params={"per_page": 10})
    if response.status_code != 200:
        raise GitHubError(f"workflow run lookup failed ({response.status_code})")
    for run in response.json().get("workflow_runs", []):
        if run.get("head_branch") != _DEPLOY_REF:
            continue
        run_id = run.get("id")
        return run_id if isinstance(run_id, int) else None
    return None


async def wait_for_dev_deploy(
    *,
    after_run_id: int | None = None,
    timeout_s: float = 20 * 60,
    poll_s: float = 15.0,
) -> tuple[str, str]:
    """Wait for the dev deploy run of a dispatch to reach a conclusion.

    ``after_run_id`` is the pre-dispatch marker recorded with
    :func:`latest_dev_deploy_run_id`: only a run on the trusted ref whose id
    is newer than the marker is accepted. Without it, the newest completed
    run on that ref could still be a deploy that predates the dispatch — or
    a run of a session that dispatched earlier — and the wait would settle
    against a revision this dispatch never put in the environment.

    Returns ``(status, detail)``: status is ``"success"``, ``"failed"``, or
    ``"timeout"``. The workflow itself ends as soon as ``docker compose up``
    returns, so success means the new revision is started, not that it is
    healthy — callers that need the environment ready still probe it.

    Runs are observed on the trusted ref :data:`_DEPLOY_REF`, the same ref
    every dispatch targets: the newest run of the workflow on that ref is
    the one the environment is converging to (the workflow's concurrency
    group cancels a superseded run), and completed runs on session branches
    are ignored rather than mistaken for our deploy. The runs endpoint is
    the workflow-scoped one: the repository-wide ``/actions/runs`` listing
    does not accept a ``workflow_id`` filter, so an unrelated completed run
    of another workflow could be mistaken for the deploy.
    """
    url = f"{_API}/repos/{settings.repo_slug}/actions/workflows/{settings.deploy_workflow}/runs"
    params = {"per_page": 10}
    deadline = asyncio.get_running_loop().time() + timeout_s

    async def our_run() -> dict | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(), params=params)
        if response.status_code != 200:
            raise GitHubError(f"workflow run lookup failed ({response.status_code})")
        for run in response.json().get("workflow_runs", []):
            if run.get("head_branch") != _DEPLOY_REF:
                continue
            run_id = run.get("id")
            if after_run_id is not None and (not isinstance(run_id, int) or run_id <= after_run_id):
                continue
            return run
        return None

    try:
        while True:
            run = await our_run()
            if run is not None and run.get("status") == "completed":
                conclusion = run.get("conclusion") or "unknown"
                status = "success" if conclusion == "success" else "failed"
                return status, f"run {run.get('html_url')} ended: {conclusion}"
            if asyncio.get_running_loop().time() >= deadline:
                return "timeout", f"dev deploy still running after {timeout_s:.0f}s"
            await asyncio.sleep(poll_s)
    except Exception as exc:
        logger.warning("waiting for the dev deploy run failed: %s", exc)
        return "failed", f"could not observe the dev deploy run: {exc}"


async def wait_for_pr_builds(
    branch: str,
    head_sha: str,
    *,
    timeout_s: float = 20 * 60,
    poll_s: float = 15.0,
) -> tuple[str, str]:
    """Wait for the build of ``head_sha`` on ``branch`` to reach a conclusion.

    The build workflow does not run on plain branch pushes: the session's
    code is only built and published when its pull request triggers it,
    under the ``pr-<number>`` tag and never ``latest``. Waiting here is what
    keeps a dev deploy from pulling the stale ``latest`` images that still
    point at main.

    The run must be the build of the exact commit the finalizer pushed, not
    merely of the branch: the branch is reused across retries, and a retried
    session force-pushes a new commit onto it. Until GitHub queues the build
    for the new head, the completed run of the earlier commit is still the
    newest one on that branch — settling on it would pass a stale
    ``pr-<number>`` image off as the one this commit produced.

    Returns ``(status, detail)``: status is ``"success"``, ``"failed"``, or
    ``"timeout"`` — the same shape as :func:`wait_for_dev_deploy`. As there,
    the polling is scoped to the build workflow's own runs endpoint, so a
    completed run of another workflow on the same branch cannot end the wait.
    """
    url = f"{_API}/repos/{settings.repo_slug}/actions/workflows/{settings.build_workflow}/runs"
    params = {"per_page": 10}
    deadline = asyncio.get_running_loop().time() + timeout_s

    async def build_for_head() -> dict | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(), params=params)
        if response.status_code != 200:
            raise GitHubError(f"build run lookup failed ({response.status_code})")
        for run in response.json().get("workflow_runs", []):
            if run.get("head_branch") == branch and run.get("head_sha") == head_sha:
                return run
        return None

    try:
        while True:
            run = await build_for_head()
            if run is not None and run.get("status") == "completed":
                conclusion = run.get("conclusion") or "unknown"
                status = "success" if conclusion == "success" else "failed"
                return status, f"build {run.get('html_url')} ended: {conclusion}"
            if asyncio.get_running_loop().time() >= deadline:
                return "timeout", f"image builds for '{branch}' at {head_sha[:7]} still running after {timeout_s:.0f}s"
            await asyncio.sleep(poll_s)
    except Exception as exc:
        logger.warning("waiting for the image build run failed: %s", exc)
        return "failed", f"could not observe the image build run: {exc}"


async def _get(path: str, params: dict[str, Any] | None = None, *, timeout_s: float = 30.0) -> Any:
    """One authenticated read of the repository. Raises on anything but 200."""
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.get(f"{_API}{path}", headers=_headers(), params=params or {})
    if response.status_code != 200:
        raise GitHubError(f"GET {path} failed ({response.status_code}): {response.text[:200]}")
    return response.json()


# One page is 100 items — GitHub's maximum — and at most this many pages are
# read for one listing. The bound exists so a pathological thread cannot turn
# one poll into hundreds of requests; it is logged when it bites, because a
# silently truncated listing is how a review goes unanswered forever.
_PAGE_SIZE = 100
_MAX_PAGES = 20


async def _get_all(path: str, params: dict[str, Any] | None = None) -> list[Any]:
    """Every page of a list endpoint, in the order GitHub returns them.

    Paginating is not optional here. These endpoints answer oldest-first and
    ignore a direction parameter, so a single page of a long thread contains
    the *oldest* entries: on a pull request with more than a hundred reviews,
    reading one page would miss every new one, permanently.
    """
    collected: list[Any] = []
    for page in range(1, _MAX_PAGES + 1):
        payload = await _get(path, {**(params or {}), "per_page": _PAGE_SIZE, "page": page})
        if not isinstance(payload, list):
            break
        collected.extend(payload)
        if len(payload) < _PAGE_SIZE:
            return collected
    logger.warning(
        "listing %s hit the %s-page ceiling (%s items); newer entries beyond it were not read",
        path,
        _MAX_PAGES,
        len(collected),
    )
    return collected


async def labelled_issues(label: str, *, since: datetime) -> list[dict[str, Any]]:
    """Open issues carrying ``label`` that were updated since ``since``.

    Pull requests are issues to this endpoint and are filtered out here: a
    pull request carrying the label is picked up through its reviews, not as
    a fresh piece of work.
    """
    payload = await _get_all(
        f"/repos/{settings.repo_slug}/issues",
        {
            "labels": label,
            "state": "open",
            "since": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sort": "created",
            "direction": "desc",
        },
    )
    return [item for item in payload if isinstance(item, dict) and "pull_request" not in item]


async def labelled_pull_requests(label: str) -> list[dict[str, Any]]:
    """Open pull requests carrying ``label``.

    The issues endpoint is the one that filters by label, so pull requests
    are read through it too — the entries it returns for them carry the
    number, which is all the review lookup needs.
    """
    payload = await _get_all(
        f"/repos/{settings.repo_slug}/issues",
        {
            "labels": label,
            "state": "open",
            "sort": "updated",
            "direction": "desc",
        },
    )
    return [item for item in payload if isinstance(item, dict) and "pull_request" in item]


async def pull_request(number: int) -> dict[str, Any]:
    """The full pull request, including its head branch and author."""
    payload = await _get(f"/repos/{settings.repo_slug}/pulls/{number}")
    return payload if isinstance(payload, dict) else {}


async def reviews_since(number: int, since: datetime) -> list[dict[str, Any]]:
    """Reviews submitted on a pull request after ``since``.

    The reviews endpoint returns oldest first and ignores a direction
    parameter, so every page is read and filtered here — asking for the last
    few would return the *first* few, and on a long-running pull request the
    newest review is on the last page, not the first.
    """
    payload = await _get_all(f"/repos/{settings.repo_slug}/pulls/{number}/reviews")
    if not isinstance(payload, list):
        return []
    fresh: list[dict[str, Any]] = []
    for review in payload:
        if not isinstance(review, dict):
            continue
        submitted = _parse_time(review.get("submitted_at"))
        if submitted is not None and submitted > since:
            fresh.append(review)
    return fresh


def _parse_time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def pr_number_from_url(pr_url: str | None) -> int | None:
    """The pull request number encoded in a github pull URL, else None."""
    if not pr_url or "/pull/" not in pr_url:
        return None
    try:
        return int(pr_url.rsplit("/pull/", 1)[1].split("/")[0])
    except (ValueError, IndexError):
        return None


async def pull_request_state(pr_url: str) -> dict[str, object] | None:
    """Fetch the current state of a pull request the session opened.

    Best effort: the UI shows what it gets and nothing depends on it, so a
    failure here is logged and swallowed rather than surfaced as an error.
    """
    number = pr_number_from_url(pr_url)
    if number is None:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{_API}/repos/{settings.repo_slug}/pulls/{number}", headers=_headers())
        if response.status_code != 200:
            return None
        payload = response.json()
    except Exception as exc:
        logger.debug("pull request lookup failed for %s: %s", pr_url, exc)
        return None

    return {
        "number": payload.get("number"),
        "state": payload.get("state"),
        "draft": payload.get("draft"),
        "merged": payload.get("merged"),
        "title": payload.get("title"),
        "additions": payload.get("additions"),
        "deletions": payload.get("deletions"),
        "changed_files": payload.get("changed_files"),
    }
