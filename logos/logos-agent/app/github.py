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
