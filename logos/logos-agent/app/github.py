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


async def wait_for_dev_deploy(*, timeout_s: float = 20 * 60, poll_s: float = 15.0) -> tuple[str, str]:
    """Wait for the dev deploy run we just dispatched to reach a conclusion.

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

    async def latest_run_on_trusted_ref() -> dict | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(), params=params)
        if response.status_code != 200:
            raise GitHubError(f"workflow run lookup failed ({response.status_code})")
        for run in response.json().get("workflow_runs", []):
            if run.get("head_branch") == _DEPLOY_REF:
                return run
        return None

    try:
        while True:
            run = await latest_run_on_trusted_ref()
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


async def wait_for_pr_builds(branch: str, *, timeout_s: float = 20 * 60, poll_s: float = 15.0) -> tuple[str, str]:
    """Wait for the branch's image builds to reach a conclusion.

    The build workflow does not run on plain branch pushes: the session's
    code is only built and published when its pull request triggers it,
    under the ``pr-<number>`` tag and never ``latest``. Waiting here is what
    keeps a dev deploy from pulling the stale ``latest`` images that still
    point at main.

    Returns ``(status, detail)``: status is ``"success"``, ``"failed"``, or
    ``"timeout"`` — the same shape as :func:`wait_for_dev_deploy`. As there,
    the polling is scoped to the build workflow's own runs endpoint, so a
    completed run of another workflow on the same branch cannot end the wait.
    """
    url = f"{_API}/repos/{settings.repo_slug}/actions/workflows/{settings.build_workflow}/runs"
    params = {"per_page": 10}
    deadline = asyncio.get_running_loop().time() + timeout_s

    async def latest_build_for_branch() -> dict | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(), params=params)
        if response.status_code != 200:
            raise GitHubError(f"build run lookup failed ({response.status_code})")
        for run in response.json().get("workflow_runs", []):
            if run.get("head_branch") == branch:
                return run
        return None

    try:
        while True:
            run = await latest_build_for_branch()
            if run is not None and run.get("status") == "completed":
                conclusion = run.get("conclusion") or "unknown"
                status = "success" if conclusion == "success" else "failed"
                return status, f"build {run.get('html_url')} ended: {conclusion}"
            if asyncio.get_running_loop().time() >= deadline:
                return "timeout", f"image builds for '{branch}' still running after {timeout_s:.0f}s"
            await asyncio.sleep(poll_s)
    except Exception as exc:
        logger.warning("waiting for the image build run failed: %s", exc)
        return "failed", f"could not observe the image build run: {exc}"


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
