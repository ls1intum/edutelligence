#!/usr/bin/env python3
"""Entrypoint of an agent session container.

Runs one task end to end: prepare a working copy, let the coding agent work,
and — if it produced anything — commit, push, and open a pull request. Progress
goes to stdout, which the runner service collects as the session transcript;
the machine-readable outcome goes to ``$LOGOS_ARTIFACT_DIR/result.json``, which
the service reads once the container exits.

Everything here runs unprivileged inside a container with no Docker socket, no
workflow-scoped token, and no route to production. That sandbox is what lets
the agent run with permission prompts disabled: there is nothing inside the
container worth protecting from it.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path("/workspace")
CHECKOUT = WORKSPACE / "repo"


def log(message: str) -> None:
    print(f"[session] {message}", flush=True)


def fail(message: str) -> None:
    print(f"[session] ERROR: {message}", file=sys.stderr, flush=True)


class Result:
    """Accumulates what the service needs to know about this run."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {
            "branch": os.environ.get("LOGOS_SESSION_BRANCH", ""),
            "pr_url": None,
            "committed": False,
            "files_changed": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_eur": 0.0,
            "error": None,
        }

    def write(self) -> None:
        directory = Path(os.environ.get("LOGOS_ARTIFACT_DIR", "/artifacts"))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "result.json").write_text(json.dumps(self.data, indent=2))
        except OSError as exc:
            fail(f"could not write result file: {exc}")


def _redact(cmd: list[str]) -> list[str]:
    """Scrub secrets from a command before it reaches the transcript.

    The transcript is persisted as agent events, rendered in the UI, and
    readable by the agent itself, so a token must never reach it — neither in
    a URL nor in a bare argument.
    """
    token = os.environ.get("GITHUB_TOKEN", "")

    def scrub(part: str) -> str:
        if token and token in part:
            part = part.replace(token, "***")
        # Generic credential-in-URL shape: https://user:password@host
        return re.sub(r"(://[^/:\s]+:)[^@\s]+(@)", r"\1***\2", part)

    return [scrub(c) for c in cmd]


def run(
    cmd: list[str], *, cwd: Path | None = None, check: bool = True, quiet: bool = False
) -> subprocess.CompletedProcess:
    """Run a command, echoing it (secrets redacted) so the transcript shows
    what happened."""
    shown = _redact(cmd)
    if not quiet:
        log(f"$ {' '.join(shlex.quote(c) for c in shown)}")
    process = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=1800)
    if process.stdout and not quiet:
        print(process.stdout, end="", flush=True)
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr, flush=True)
    if check and process.returncode != 0:
        raise RuntimeError(f"command failed ({process.returncode}): {' '.join(shown)}")
    return process


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _install_git_askpass(token: str) -> None:
    """Teach git to read the push token from the environment, never a URL.

    A credential-in-URL remote would persist the token into .git/config on
    the workspace volume — which outlives the container — and any echo of the
    URL would land it in the transcript. The askpass helper keeps the token
    in the process environment only: git prompts for it on an authenticated
    fetch or push, the helper answers from GITHUB_TOKEN, and nothing on disk
    or in the log ever carries it. Anonymous clones of the public repository
    need no credential at all.
    """
    if not token:
        return
    helper = Path("/tmp") / "logos-git-askpass.sh"
    helper.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  Username*) printf "%s\\n" "x-access-token" ;;\n'
        '  *) printf "%s\\n" "$GITHUB_TOKEN" ;;\n'
        "esac\n"
    )
    helper.chmod(0o700)
    os.environ["GIT_ASKPASS"] = str(helper)
    # Never fall back to a terminal prompt: without the helper, fail fast.
    os.environ["GIT_TERMINAL_PROMPT"] = "0"


def _reset_agent_home() -> None:
    """Replace the agent's home with a fresh, empty directory.

    HOME lives on the workspace volume, so everything a previous session
    wrote there survives its container: a ``.gitconfig`` with
    ``core.hooksPath`` or an alias, a ``.claude/settings.json`` whose hooks
    run at the next session's first tool call, a ``CLAUDE.md`` the CLI
    injects as global memory, shell rc files, and tool caches (maven, npm,
    pip) a session could have poisoned to steer the next build. Every one of
    those is agent-writable while the agent holds a push token, and the next
    session is credential-bearing — so none of it is safe to reuse. The
    re-download cost is the price of a clean start; the only state worth
    keeping across sessions is the working copy itself, and even its
    repository metadata is rebuilt, not reused.
    """
    home = Path(os.environ.get("HOME") or "/workspace/.home")
    if home.is_symlink() or not home.is_dir():
        if home.exists():
            home.unlink()
    else:
        shutil.rmtree(home)
    home.mkdir(parents=True, exist_ok=True)


def _rebuild_git_metadata(repo_url: str) -> None:
    """Recreate the checkout's ``.git`` from scratch, keeping only objects.

    Everything except ``objects/`` is agent-writable, and parts of it are
    agent-executable: git runs hook scripts from ``.git/hooks`` — or
    wherever ``core.hooksPath`` in the repository (or global) config points
    — on fetch, commit, and push. A bypass-permissions session can install
    such a hook in minutes, and ``reset``/``clean`` never remove it, so it
    would run from this harness with the *next* session's credentials.
    Deleting the metadata and re-initialising leaves the standard config,
    sample hooks only, and the object store — content-addressed data git
    reads, never executes, and the one part worth keeping. The agent's home
    is reset before this is called, because git reads the global
    configuration (including the initialisation template) from there.
    """
    git_dir = CHECKOUT / ".git"
    keep_objects = (git_dir / "objects").is_dir()
    for entry in git_dir.iterdir():
        if keep_objects and entry.name == "objects":
            continue
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)
    run(["git", "init", "--quiet"], cwd=CHECKOUT, quiet=True)
    run(["git", "remote", "add", "origin", repo_url], cwd=CHECKOUT, quiet=True)


def prepare_checkout(repo_url: str, base_branch: str, branch: str, token: str) -> None:
    """Get a clean working copy of `base_branch` on a fresh `branch`.

    A session runs unprivileged but with permission prompts disabled and a
    push token in its environment, so the *next* session must not trust
    anything the previous one wrote: the home directory is replaced and the
    repository metadata rebuilt before any git command runs.
    """
    _install_git_askpass(token)
    _reset_agent_home()
    if not (CHECKOUT / ".git").is_dir():
        log(f"cloning {repo_url} at {base_branch}")
        CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
        if CHECKOUT.exists():
            # A previous session left a tree without a usable .git (or one
            # it replaced): nothing in it is trusted, so start from nothing.
            if CHECKOUT.is_dir() and not CHECKOUT.is_symlink():
                shutil.rmtree(CHECKOUT)
            else:
                CHECKOUT.unlink()
        run(["git", "clone", "--depth", "50", "--branch", base_branch, repo_url, str(CHECKOUT)])
    else:
        log("reusing existing checkout; rebuilding trusted git metadata")
        _rebuild_git_metadata(repo_url)
        run(["git", "fetch", "--depth", "50", "origin", base_branch], cwd=CHECKOUT)
        # Discard whatever a previous session left behind: a session starts
        # from the base branch, never from another session's leftovers.
        run(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=CHECKOUT)
        run(["git", "clean", "-fdx"], cwd=CHECKOUT, check=False)

    run(["git", "config", "user.name", "Logos Agent"], cwd=CHECKOUT, quiet=True)
    run(
        ["git", "config", "user.email", "logos-agent@users.noreply.github.com"],
        cwd=CHECKOUT,
        quiet=True,
    )
    # -B so a retried session reuses its branch name instead of failing.
    run(["git", "checkout", "-B", branch], cwd=CHECKOUT)


def build_prompt(task: str) -> str:
    """Wrap the operator's task with the constraints of this environment."""
    return (
        f"{task}\n\n"
        "--- Environment notes ---\n"
        "You are running unattended in an isolated container on a working copy "
        "of this repository. There is no human to ask, so make reasonable "
        "decisions and state your assumptions in the final summary.\n"
        "- Work only inside the current checkout.\n"
        "- Do not run git commit, git push, or gh: the harness commits and "
        "opens the pull request for you after you finish.\n"
        "- Run the project's tests or linters for the code you touch, and fix "
        "what you break.\n"
        "- If the task turns out to be impossible or already done, say so "
        "plainly instead of inventing changes.\n"
    )


def run_agent(task: str) -> dict[str, object]:
    """Drive the coding agent and return what it reported about the run."""
    prompt = build_prompt(task)
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        # Safe here precisely because of the sandbox: no socket, no secrets,
        # no production access. Prompting would deadlock an unattended run.
        "--permission-mode",
        "bypassPermissions",
    ]
    max_turns = os.environ.get("LOGOS_SESSION_MAX_TURNS", "").strip()
    if max_turns.isdigit():
        cmd += ["--max-turns", max_turns]

    log("starting agent")
    started = time.monotonic()
    usage: dict[str, object] = {}

    process = subprocess.Popen(cmd, cwd=CHECKOUT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        # The stream is newline-delimited JSON; anything that is not valid JSON
        # is the CLI talking to us directly, and is worth showing verbatim.
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            print(line, flush=True)
            continue
        _render_event(event)
        if event.get("type") == "result":
            usage = event
    code = process.wait()
    elapsed = time.monotonic() - started
    log(f"agent finished in {elapsed:.0f}s with exit code {code}")
    if code != 0:
        raise RuntimeError(f"agent exited with code {code}")
    return usage


def _render_event(event: dict) -> None:
    """Turn one stream event into a readable transcript line."""
    kind = event.get("type")
    if kind == "assistant":
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                print(block["text"].strip(), flush=True)
            elif block.get("type") == "tool_use":
                print(f"[tool] {block.get('name')}", flush=True)
    elif kind == "result":
        subtype = event.get("subtype", "")
        print(f"[result] {subtype}", flush=True)
    elif kind == "system" and event.get("subtype") == "init":
        print(f"[agent] model={event.get('model')}", flush=True)


def usage_totals(usage: dict[str, object]) -> tuple[int, int, float]:
    """Extract token counts and cost from the agent's result event."""
    tokens = usage.get("usage") or {}
    if not isinstance(tokens, dict):
        tokens = {}

    def as_int(*keys: str) -> int:
        for key in keys:
            value = tokens.get(key)
            if isinstance(value, int):
                return value
        return 0

    tokens_in = as_int("input_tokens") + as_int("cache_creation_input_tokens") + as_int("cache_read_input_tokens")
    tokens_out = as_int("output_tokens")
    # The CLI reports USD; Logos accounts in EUR. Without a live rate the
    # honest thing is to carry the number through unconverted and let the
    # platform's own billing be the authority.
    cost = usage.get("total_cost_usd")
    return tokens_in, tokens_out, float(cost) if isinstance(cost, (int, float)) else 0.0


def changed_files() -> list[str]:
    process = run(["git", "status", "--porcelain"], cwd=CHECKOUT, check=False, quiet=True)
    return [line[3:] for line in process.stdout.splitlines() if line.strip()]


def commit_and_push(branch: str, task: str) -> int:
    files = changed_files()
    if not files:
        log("agent produced no changes; nothing to commit")
        return 0

    log(f"committing {len(files)} changed file(s)")
    run(["git", "add", "-A"], cwd=CHECKOUT)
    subject = _commit_subject(task)
    message = (
        f"{subject}\n\n"
        f"Produced by an unattended Logos agent session "
        f"({os.environ.get('LOGOS_SESSION_ID', '?')}).\n\n"
        f"Task:\n{task.strip()[:2000]}\n"
    )
    run(["git", "commit", "-m", message], cwd=CHECKOUT)
    run(["git", "push", "--force-with-lease", "origin", branch], cwd=CHECKOUT)
    return len(files)


def _commit_subject(task: str) -> str:
    """Derive a commit subject that satisfies the repository's title policy.

    The repo requires `` `Logos`: Capitalised … `` on pull requests, and CI
    enforces it. Producing it here rather than asking the agent for it means a
    session cannot fail review on a formatting rule.
    """
    first_line = task.strip().splitlines()[0] if task.strip() else "Agent session"
    cleaned = re.sub(r"\s+", " ", first_line).strip().rstrip(".")
    cleaned = re.sub(r"^`?logos`?\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        cleaned = "Agent session"
    cleaned = cleaned[0].upper() + cleaned[1:]
    return f"`Logos`: {cleaned[:88]}"


def open_pull_request(branch: str, base_branch: str, task: str) -> str | None:
    slug = os.environ.get("LOGOS_REPO_SLUG", "").strip()
    if not slug:
        log("no repository slug configured; skipping pull request")
        return None

    title = _commit_subject(task)
    body = (
        "## Summary\n\n"
        "Opened by an unattended Logos agent session running on spare platform "
        "capacity. **Nothing here has been reviewed by a human yet.**\n\n"
        "## Task given to the agent\n\n"
        f"```\n{task.strip()[:4000]}\n```\n\n"
        "## Steps for Testing\n\n"
        "1. Read the diff — this is the first point a person sees this work.\n"
        "2. Check that the tests the agent ran actually cover the change.\n\n"
        f"Session: `{os.environ.get('LOGOS_SESSION_ID', '?')}`\n"
    )
    process = run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        ],
        cwd=CHECKOUT,
        check=False,
    )
    if process.returncode != 0:
        # An existing pull request for this branch is not a failure: a retried
        # session should reuse it.
        existing = run(
            ["gh", "pr", "view", branch, "--repo", slug, "--json", "url", "--jq", ".url"],
            cwd=CHECKOUT,
            check=False,
            quiet=True,
        )
        url = existing.stdout.strip()
        if url:
            log(f"reusing existing pull request {url}")
            return url
        fail("could not open a pull request")
        return None

    for line in process.stdout.splitlines():
        if line.startswith("https://"):
            return line.strip()
    return None


def main() -> int:
    result = Result()
    try:
        task = require_env("LOGOS_SESSION_TASK")
        branch = require_env("LOGOS_SESSION_BRANCH")
        base_branch = os.environ.get("LOGOS_SESSION_BASE_BRANCH", "main")
        repo_url = require_env("LOGOS_REPO_URL")
        token = os.environ.get("GITHUB_TOKEN", "")

        if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            raise RuntimeError("no Logos key provided; the agent has no model to call")

        prepare_checkout(repo_url, base_branch, branch, token)
        usage = run_agent(task)

        tokens_in, tokens_out, cost = usage_totals(usage)
        result.data.update(tokens_in=tokens_in, tokens_out=tokens_out, cost_eur=cost)

        if token:
            count = commit_and_push(branch, task)
            result.data["files_changed"] = count
            result.data["committed"] = count > 0
            if count and os.environ.get("LOGOS_SESSION_OPEN_PR") == "1":
                result.data["pr_url"] = open_pull_request(branch, base_branch, task)
        else:
            log("no GitHub token provided; leaving changes uncommitted in the workspace")

        # Screenshots are the runner's job, taken after settlement: a
        # session's own view of the dev environment is stale the moment its
        # deploy is queued, and the runner is the one that knows when the
        # deploy has landed.
        log("session complete")
        return 0
    except Exception as exc:
        fail(str(exc))
        result.data["error"] = str(exc)
        return 1
    finally:
        result.write()


if __name__ == "__main__":
    sys.exit(main())
