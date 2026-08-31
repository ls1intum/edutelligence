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


async def dispatch_dev_deploy(*, ref: str, image_tag: str = "latest") -> str:
    """Trigger the dev deployment workflow and return a link to the run.

    Refuses any workflow other than the dev one. The dev deploy workflow is
    itself pinned to the dev environment, so this is two independent locks on
    the same door.
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
            json={"ref": ref, "inputs": {"image-tag": image_tag}},
        )
    if response.status_code not in (201, 204):
        raise GitHubError(f"workflow dispatch failed ({response.status_code}): {response.text}")

    return f"https://github.com/{settings.repo_slug}/actions/workflows/{workflow}"


async def wait_for_dev_deploy(ref: str, *, timeout_s: float = 20 * 60, poll_s: float = 15.0) -> tuple[str, str]:
    """Wait for the dev deploy run we just dispatched to reach a conclusion.

    Returns ``(status, detail)``: status is ``"success"``, ``"failed"``, or
    ``"timeout"``. The workflow itself ends as soon as ``docker compose up``
    returns, so success means the new revision is started, not that it is
    healthy — callers that need the environment ready still probe it.
    """
    url = f"{_API}/repos/{settings.repo_slug}/actions/runs"
    params = {"workflow_id": settings.deploy_workflow, "per_page": 10}
    deadline = asyncio.get_running_loop().time() + timeout_s

    async def latest_run_for_ref() -> dict | None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(), params=params)
        if response.status_code != 200:
            raise GitHubError(f"workflow run lookup failed ({response.status_code})")
        for run in response.json().get("workflow_runs", []):
            if run.get("head_branch") == ref:
                return run
        return None

    try:
        while True:
            run = await latest_run_for_ref()
            if run is not None and run.get("status") == "completed":
                conclusion = run.get("conclusion") or "unknown"
                status = "success" if conclusion == "success" else "failed"
                return status, f"run {run.get('html_url')} ended: {conclusion}"
            if asyncio.get_running_loop().time() >= deadline:
                return "timeout", f"dev deploy for '{ref}' still running after {timeout_s:.0f}s"
            await asyncio.sleep(poll_s)
    except Exception as exc:
        logger.warning("waiting for the dev deploy run failed: %s", exc)
        return "failed", f"could not observe the dev deploy run: {exc}"


async def pull_request_state(pr_url: str) -> dict[str, object] | None:
    """Fetch the current state of a pull request the session opened.

    Best effort: the UI shows what it gets and nothing depends on it, so a
    failure here is logged and swallowed rather than surfaced as an error.
    """
    if not pr_url or "/pull/" not in pr_url:
        return None
    try:
        number = int(pr_url.rsplit("/pull/", 1)[1].split("/")[0])
    except (ValueError, IndexError):
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
