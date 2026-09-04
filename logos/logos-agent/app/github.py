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

from . import attachments
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
    collected, _ = await _get_all_bounded(path, params)
    return collected


async def _get_all_bounded(path: str, params: dict[str, Any] | None = None) -> tuple[list[Any], bool]:
    """The same listing, and whether the page ceiling cut it short.

    A caller that tells an agent "this is the whole conversation" needs the
    second half of that answer: two thousand entries read out of more is
    incomplete context, and indistinguishable from a complete read without
    it.
    """
    collected: list[Any] = []
    for _ in range(_MAX_PAGES):
        page = len(collected) // _PAGE_SIZE + 1
        payload = await _get(path, {**(params or {}), "per_page": _PAGE_SIZE, "page": page})
        if not isinstance(payload, list):
            # A 200 that is not a list is not an empty listing: something
            # answered, and it was not this endpoint. Reported as incomplete
            # rather than as "nothing more to read".
            logger.info("listing %s answered with %s, not a list", path, type(payload).__name__)
            return collected, True
        collected.extend(payload)
        if len(payload) < _PAGE_SIZE:
            return collected, False
    logger.warning(
        "listing %s hit the %s-page ceiling (%s items); newer entries beyond it were not read",
        path,
        _MAX_PAGES,
        len(collected),
    )
    return collected, True


async def _assigned(login: str) -> list[dict[str, Any]]:
    """Every open issue and pull request assigned to an account.

    One listing for both: to this endpoint a pull request *is* an issue, and
    the entries it returns carry the number and title, which is all the
    callers need. No time filter — assignment is the signal, and a session
    that already answered one is remembered by its reference, so an issue
    assigned months ago is picked up once and then left alone.
    """
    payload = await _get_all(
        f"/repos/{settings.repo_slug}/issues",
        {"assignee": login, "state": "open", "sort": "updated", "direction": "desc"},
    )
    return [item for item in payload if isinstance(item, dict)]


async def assigned_issues(login: str) -> list[dict[str, Any]]:
    """Open issues assigned to an account — pull requests excluded."""
    return [item for item in await _assigned(login) if "pull_request" not in item]


async def assigned_pull_requests(login: str) -> list[dict[str, Any]]:
    """Open pull requests assigned to an account."""
    return [item for item in await _assigned(login) if "pull_request" in item]


async def authored_pull_requests(login: str) -> list[dict[str, Any]]:
    """Open pull requests an account opened.

    Its own pull requests are the ones whose reviews it has to answer, and
    they are not necessarily assigned to it — GitHub does not assign an
    author to their own pull request.
    """
    payload = await _get_all(
        f"/repos/{settings.repo_slug}/pulls",
        {"state": "open", "sort": "updated", "direction": "desc"},
    )
    wanted = login.strip().lower()
    return [
        pull
        for pull in payload
        if isinstance(pull, dict) and str(((pull.get("user") or {}).get("login")) or "").lower() == wanted
    ]


async def pull_request(number: int) -> dict[str, Any]:
    """The full pull request, including its head branch and author."""
    payload = await _get(f"/repos/{settings.repo_slug}/pulls/{number}")
    return payload if isinstance(payload, dict) else {}


async def latest_changes_requested_review(number: int) -> dict[str, Any] | None:
    """The open request for changes on a pull request, if there is one.

    GitHub tracks an opinion *per reviewer*, and so does this. Each
    reviewer's latest opinionated review — `APPROVED` or
    `CHANGES_REQUESTED` — is their current position; a `COMMENTED` review is
    not an opinion and does not clear one, and a `DISMISSED` review is a
    withdrawn one. The newest request for changes among the reviewers who
    currently hold that position is the work.

    A single globally newest review would get this wrong in both
    directions: reviewer B approving would appear to withdraw reviewer A's
    objection, and anybody's passing comment would bury it.

    Every page is read: the endpoint answers oldest-first and ignores a
    direction parameter, so on a long-running pull request the newest
    review is on the last page, not the first.
    """
    payload = await _get_all(f"/repos/{settings.repo_slug}/pulls/{number}/reviews")
    if not isinstance(payload, list):
        return None

    # Per reviewer: their latest opinionated review, in submission order.
    positions: dict[str, tuple[datetime | None, dict[str, Any]]] = {}
    for review in payload:
        if not isinstance(review, dict) or not isinstance(review.get("id"), int):
            continue
        state = str(review.get("state") or "").upper()
        if state not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            # COMMENTED and PENDING say nothing about whether the reviewer
            # is still asking for changes.
            continue
        author = str((review.get("user") or {}).get("login") or "")
        if not author:
            continue
        submitted = _parse_time(review.get("submitted_at"))
        held = positions.get(author)
        if held is None or submitted is None or held[0] is None or submitted >= held[0]:
            positions[author] = (submitted, review)

    outstanding = [
        (submitted, review)
        for submitted, review in positions.values()
        if str(review.get("state") or "").upper() == "CHANGES_REQUESTED"
    ]
    if not outstanding:
        return None
    # The newest of the open objections: one session answers the review it
    # names, and the others are seen again once it has.
    outstanding.sort(key=lambda item: (item[0] is not None, item[0] or datetime.min.replace(tzinfo=timezone.utc)))
    return outstanding[-1][1]


async def review_comments(number: int, review_id: int) -> list[dict[str, Any]]:
    """The inline comments belonging to one submitted review.

    A review's body and its inline comments are separate objects, and most
    reviews put the substance in the inline ones — a changes-requested
    review with an empty body and six inline comments is the normal shape.
    Queueing work from the body alone would hand the agent a task with none
    of the requested changes in it.
    """
    payload = await _get_all(f"/repos/{settings.repo_slug}/pulls/{number}/reviews/{review_id}/comments")
    return [comment for comment in payload if isinstance(comment, dict)]


# GitHub answers an attachment link with a redirect to signed storage, and
# that storage may take a few hops to reach.
_MAX_REDIRECTS = 5


async def fetch_image(url: str, *, max_bytes: int) -> tuple[bytes, str] | None:
    """Download an image a request refers to, or None if it is not one.

    Authenticated, because an attachment on a private repository needs the
    token; bounded, because this is a fetch of a URL that came out of text a
    stranger can write. Redirects are followed — GitHub answers attachment
    links with one — and anything that is not an image, or is too big, is
    left alone.
    """
    if not attachments.from_github(url):
        # The only URLs worth following are the ones GitHub serves itself.
        # Everything else in an issue body is a host its author chose.
        logger.info("not fetching %s: not a GitHub attachment", url)
        return None
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        target = url
        for _ in range(_MAX_REDIRECTS):
            # Derived per hop rather than carried along: the credential goes
            # to GitHub or to nobody.
            headers = _headers() if attachments.may_carry_the_token(target) else {}
            async with client.stream("GET", target, headers=headers) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    if not location:
                        return None
                    target = str(httpx.URL(target).join(location))
                    if not attachments.is_public(target):
                        # A redirect into the runner's own network is not a
                        # picture; it is the fetch being aimed at us.
                        logger.info("refusing to follow %s to %s", url, target)
                        return None
                    continue
                if response.status_code != 200:
                    logger.info("could not fetch %s: %s", url, response.status_code)
                    return None
                content_type = response.headers.get("content-type", "")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        logger.info("attachment %s is larger than %s bytes; leaving it", url, max_bytes)
                        return None
                return bytes(body), content_type
    logger.info("gave up following redirects for %s", url)
    return None


async def open_pull_request_for(branch: str) -> dict[str, Any] | None:
    """The open pull request whose head is this branch, if there is one.

    What decides whether a workspace is still needed: while a pull request
    is open its work is not finished, however long the checkout has been
    idle, and the conversation kept beside that checkout is what the next
    review continues rather than starting over.
    """
    if not branch:
        return None
    owner = settings.repo_slug.split("/", 1)[0]
    try:
        payload = await _get(
            f"/repos/{settings.repo_slug}/pulls",
            {"head": f"{owner}:{branch}", "state": "open", "per_page": 1},
        )
    except GitHubError as exc:
        logger.info("could not establish whether '%s' still has an open pull request: %s", branch, exc)
        raise
    if isinstance(payload, list) and payload:
        return payload[0]
    return None


async def pull_request_conversation(number: int, *, limit: int = 40) -> tuple[list[dict[str, Any]], list[str]]:
    """Everything said on a pull request, oldest last, and what is missing.

    The second half of the answer is the point: a source that failed reads
    exactly like a source with nothing in it, and the task built from this
    tells the agent the conversation is complete. A transient failure would
    then hide requested changes behind a sentence saying nothing is hidden.

    The agent phase holds no GitHub credential and has no network, so a
    conversation it is asked to continue has to travel with its task. Asking
    it to "read the review" without this is asking it to spend its turns
    discovering that it cannot.

    Three sources, because GitHub keeps them apart: submitted reviews (a
    verdict and often an empty body), the inline comments that carry what
    those reviews actually said, and the discussion under the pull request.
    """
    reviews, inline, discussion = await asyncio.gather(
        _get_all_bounded(f"/repos/{settings.repo_slug}/pulls/{number}/reviews"),
        _get_all_bounded(f"/repos/{settings.repo_slug}/pulls/{number}/comments"),
        _get_all_bounded(f"/repos/{settings.repo_slug}/issues/{number}/comments"),
        return_exceptions=True,
    )
    entries: list[dict[str, Any]] = []
    missing: list[str] = []

    def add(answer: object, kind: str) -> None:
        if not isinstance(answer, tuple):
            # One source failing is not worth losing the other two over: a
            # partial conversation still beats none — as long as it says so.
            logger.info("could not read the %s of #%s: %s", kind, number, answer)
            missing.append(kind)
            return
        items, truncated = answer
        if truncated:
            # More than the listing ceiling: what was read is the oldest
            # part, so the newest — the part still open — is what is gone.
            missing.append(f"{kind} beyond the first {len(items)}")
        for item in items:
            if not isinstance(item, dict):
                continue
            body = str(item.get("body") or "").strip()
            state = str(item.get("state") or "").replace("_", " ").lower()
            if not body and state not in ("changes requested", "approved"):
                continue
            entries.append(
                {
                    "kind": kind,
                    "author": str((item.get("user") or {}).get("login") or "somebody"),
                    "at": _parse_time(item.get("submitted_at") or item.get("created_at")),
                    "path": item.get("path"),
                    "line": item.get("line") or item.get("original_line"),
                    "state": state,
                    "body": body,
                }
            )

    add(reviews, "reviews")
    add(inline, "inline comments")
    add(discussion, "comments")
    entries.sort(key=lambda entry: entry["at"] or datetime.min.replace(tzinfo=timezone.utc))
    # The newest are the ones still open; an old conversation is history.
    # Said rather than silently dropped, though: an early review comment
    # nobody answered is exactly the kind of thing that falls off the end,
    # and the task built from this claims to be complete.
    if len(entries) > limit:
        missing = [*missing, f"{len(entries) - limit} older comment(s), beyond what fits in a task"]
    return entries[-limit:], missing


async def recent_issue_comments(since: datetime) -> list[dict[str, Any]]:
    """Every issue and pull-request comment in the repository since ``since``.

    One repository-wide listing rather than one request per thread: the
    agent has to notice a question on a pull request nobody assigned it, and
    walking every open thread to find that would cost a request each.
    """
    return [
        comment
        for comment in await _get_all(
            f"/repos/{settings.repo_slug}/issues/comments",
            {"since": _stamp(since), "sort": "created", "direction": "desc"},
        )
        if isinstance(comment, dict)
    ]


async def recent_review_comments(since: datetime) -> list[dict[str, Any]]:
    """Every inline review comment in the repository since ``since``."""
    return [
        comment
        for comment in await _get_all(
            f"/repos/{settings.repo_slug}/pulls/comments",
            {"since": _stamp(since), "sort": "created", "direction": "desc"},
        )
        if isinstance(comment, dict)
    ]


def issue_number_of(comment: dict[str, Any]) -> int | None:
    """The issue or pull request an issue comment belongs to.

    The repository-wide listing does not carry the number as a field; it is
    the last segment of the thread's API url.
    """
    url = str(comment.get("issue_url") or "")
    return _trailing_number(url)


def pull_number_of(comment: dict[str, Any]) -> int | None:
    """The pull request an inline review comment belongs to."""
    url = str(comment.get("pull_request_url") or "")
    return _trailing_number(url)


def thread_root_of(comment: dict[str, Any]) -> int | None:
    """The inline thread a review comment belongs to.

    A reply carries the id of the comment that started the thread; the
    starter carries its own. Answering a line-specific question means
    answering *in that thread*, so the root is what identifies it — a whole
    pull request's inline comments are several conversations, not one.
    """
    root = comment.get("in_reply_to_id")
    if isinstance(root, int):
        return root
    own = comment.get("id")
    return own if isinstance(own, int) else None


def created_at_of(comment: dict[str, Any]) -> datetime | None:
    """When a comment was written.

    Issue comments and review comments have independent id sequences, so a
    newer comment can carry a smaller id than an older one of the other
    kind. Time is the only order the two share.
    """
    return _parse_time(comment.get("created_at"))


def _trailing_number(url: str) -> int | None:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Repository permissions that mean "may change this code". GitHub's
# `read` and `none` do not.
_WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})


async def may_push(login: str) -> bool:
    """Whether an account may write to this repository.

    On a public repository anybody can comment, review, and ask the agent
    for things. What they cannot do is push — and a session that commits on
    their say-so would push for them. So the ability to direct code changes
    is checked against the repository's own collaborator permissions, not
    inferred from being able to type in a comment box.

    A lookup that fails answers False: an unknown permission is not a
    permission.
    """
    if not login:
        return False
    try:
        payload = await _get(f"/repos/{settings.repo_slug}/collaborators/{login}/permission")
    except GitHubError as exc:
        # 404 is the ordinary answer for "not a collaborator".
        logger.info("could not establish repository permission for %s: %s", login, exc)
        return False
    return str(payload.get("permission") or "").lower() in _WRITE_PERMISSIONS


# What a session's stage looks like on a thread. GitHub's palette is fixed
# — +1, -1, laugh, confused, heart, hooray, rocket, eyes — so there is no
# hourglass to wait with: eyes means seen and in the queue, a rocket means
# it is being worked on now, and a shrug means it did not work out. Three
# reactions, no notifications, and a person can see where their request is
# without asking.
REACTION_QUEUED = "eyes"
REACTION_RUNNING = "rocket"
REACTION_FAILED = "confused"


async def react(path: str, content: str = REACTION_QUEUED) -> bool:
    """Leave a reaction, so a person can see their request was picked up.

    ``path`` is the API path of the thing reacted to — an issue, an issue
    comment, or an inline review comment. Returns whether the reaction is
    there now; a duplicate (GitHub answers 200 instead of 201) counts, since
    the point is the state, not who created it.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{_API}{path}/reactions", headers=_headers(), json={"content": content})
    if response.status_code in (200, 201):
        return True
    raise GitHubError(f"reaction on {path} failed ({response.status_code}): {response.text[:200]}")


async def post_issue_comment(number: int, body: str) -> str:
    """Answer in an issue or pull-request thread. Returns the comment url."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_API}/repos/{settings.repo_slug}/issues/{number}/comments",
            headers=_headers(),
            json={"body": body},
        )
    if response.status_code != 201:
        raise GitHubError(f"comment on #{number} failed ({response.status_code}): {response.text[:200]}")
    return str(response.json().get("html_url") or "")


async def reply_to_review_comment(number: int, comment_id: int, body: str) -> str:
    """Answer inside an inline review thread. Returns the comment url.

    The reply lands in the thread the question was asked in, which is where
    its author is looking — a top-level comment would answer a line-specific
    question somewhere else entirely.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_API}/repos/{settings.repo_slug}/pulls/{number}/comments/{comment_id}/replies",
            headers=_headers(),
            json={"body": body},
        )
    if response.status_code != 201:
        raise GitHubError(
            f"reply to comment {comment_id} on #{number} failed ({response.status_code}): {response.text[:200]}"
        )
    return str(response.json().get("html_url") or "")


def head_of(pull: dict[str, Any]) -> tuple[str, str]:
    """A pull request's head branch and the repository it lives in.

    Returns ``("", "")`` when the payload does not carry a usable head — a
    deleted branch, or a shape this code does not know. Callers treat that
    as "not something to work on" rather than guessing.
    """
    head = pull.get("head") or {}
    ref = str(head.get("ref") or "")
    repo = ((head.get("repo") or {}).get("full_name")) or ""
    return ref, str(repo)


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
