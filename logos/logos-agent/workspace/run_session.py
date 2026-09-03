#!/usr/bin/env python3
"""Entrypoint of an agent session container.

One session runs in three phases of this image, selected by
``LOGOS_SESSION_PHASE`` and run by the runner as separate containers:

* ``prepare`` — trusted, with egress and the scoped push token: clone or
  reset the working copy, rebuild its git metadata, and replace the agent's
  home.
* ``agent`` — untrusted, no reusable credentials, and its only network peer
  is the credential-injecting model gateway: the coding agent does the work.
* ``finalize`` — trusted, with the push token: bring the agent-owned
  checkout and home under trusted metadata again, install the transient
  askpass helper, then commit, push, and open the pull request before
  updating the result file.

Progress goes to stdout, which the runner service collects as the session
transcript; the machine-readable outcome goes to
``$LOGOS_ARTIFACT_DIR/result.json``, which the service reads once the session
has settled.

Everything here runs unprivileged inside a container with no Docker socket, no
workflow-scoped token, and no route to production. That sandbox is what lets
the agent run with permission prompts disabled: there is nothing inside the
agent phase worth protecting from it — and the two trusted phases only ever
run fixed harness code, never the agent.
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
            "cost_usd": 0.0,
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
    if home.is_symlink():
        # Unlinked even when the target does not exist: `exists()` follows
        # the link, so a dangling one is invisible to it — but `mkdir`
        # would fail on the surviving path and break every later session.
        home.unlink()
    elif home.is_dir():
        shutil.rmtree(home)
    elif home.exists():
        home.unlink()
    home.mkdir(parents=True, exist_ok=True)


def _clear_checkout() -> None:
    """Remove whatever a previous session left at the checkout path.

    Same symlink rule as the home: a dangling ``/workspace/repo`` link is
    invisible to ``exists()``, yet ``git clone`` fails on the surviving
    path — left alone, one session could make every later session in the
    workspace fail before the agent even starts.
    """
    if CHECKOUT.is_symlink():
        CHECKOUT.unlink()
    elif CHECKOUT.is_dir():
        # A previous session left a tree without a usable .git (or one it
        # replaced): nothing in it is trusted, so start from nothing.
        shutil.rmtree(CHECKOUT)
    elif CHECKOUT.exists():
        CHECKOUT.unlink()


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

    Symlinks count as agent-writable too: a ``.git`` — or an ``objects`` —
    that is a link into another tree would be followed by anything that
    reads it, so links are unlinked, never traversed.
    """
    git_dir = CHECKOUT / ".git"
    if git_dir.is_symlink() or (git_dir.exists() and not git_dir.is_dir()):
        # The metadata itself replaced by a link to another repository (or a
        # plain file): following it would wipe and reinitialise the target's
        # .git, so the path is unlinked and re-initialised from nothing.
        git_dir.unlink()
    elif git_dir.is_dir():
        objects = git_dir / "objects"
        # The object store is kept only when it is a real directory: a link
        # named ``objects`` would make git read and write its store through
        # the target, and the target belongs to no repository we own.
        keep_objects = objects.is_dir() and not objects.is_symlink()
        for entry in git_dir.iterdir():
            if entry.is_symlink():
                entry.unlink()
            elif keep_objects and entry.name == "objects":
                continue
            elif entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
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
    if CHECKOUT.is_symlink() or (CHECKOUT.exists() and not CHECKOUT.is_dir()):
        # A session may have replaced the checkout itself with a link: the
        # `.git` check below would follow it into another tree and treat
        # that tree's metadata as this workspace's. The work behind a link
        # is not a working copy of this workspace, so the path is unlinked
        # and the repository comes back as a fresh clone.
        CHECKOUT.unlink()
    if not (CHECKOUT / ".git").is_dir():
        log(f"cloning {repo_url} at {base_branch}")
        CHECKOUT.parent.mkdir(parents=True, exist_ok=True)
        _clear_checkout()
        run(["git", "clone", "--depth", "50", "--branch", base_branch, repo_url, str(CHECKOUT)])
    else:
        log("reusing existing checkout; rebuilding trusted git metadata")
        _rebuild_git_metadata(repo_url)
        run(["git", "fetch", "--depth", "50", "origin", base_branch], cwd=CHECKOUT)
        # Discard whatever a previous session left behind: a session starts
        # from the base branch, never from another session's leftovers.
        run(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=CHECKOUT)
        run(["git", "clean", "-fdx"], cwd=CHECKOUT, check=False)

    _configure_git_identity()
    # -B so a retried session reuses its branch name instead of failing.
    run(["git", "checkout", "-B", branch], cwd=CHECKOUT)


def agent_login() -> str:
    """The GitHub account this session's work belongs to."""
    return (os.environ.get("LOGOS_AGENT_GITHUB_LOGIN") or "LogosOSSAgent").strip()


def _configure_git_identity() -> None:
    """Commit as the agent account, not as an anonymous 'Logos Agent'.

    The account is the same one the token belongs to, so a commit's author
    and the identity that pushed it agree — the history then shows one
    revocable actor rather than a name that resembles the platform.
    """
    login = agent_login()
    run(["git", "config", "user.name", login], cwd=CHECKOUT, quiet=True)
    run(
        ["git", "config", "user.email", f"{login}@users.noreply.github.com"],
        cwd=CHECKOUT,
        quiet=True,
    )


def verify_token_identity(token: str) -> None:
    """Refuse to push with a token that is not the agent account's.

    The runner checks this at startup, but the container is where the push
    actually happens, and it is the last place the check still helps: a
    token swapped in the environment, or a runner that started before the
    token was rotated, would otherwise commit and open pull requests under
    a human contributor's name.
    """
    expected = agent_login().lower()
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        cwd=str(CHECKOUT) if CHECKOUT.is_dir() else None,
        capture_output=True,
        text=True,
        env={**os.environ, "GH_TOKEN": token, "GITHUB_TOKEN": token},
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"could not establish the identity of the push token: {result.stderr.strip()[:200]}")
    login = (result.stdout or "").strip()
    if login.lower() != expected:
        raise RuntimeError(
            f"the push token authenticates as '{login}', not as the agent account "
            f"'{agent_login()}'; refusing to push agent work under another identity"
        )
    log(f"push token verified as {login}")


def finalize_checkout(repo_url: str, base_branch: str, branch: str, token: str) -> bool:
    """Bring the agent's working tree under trusted metadata, then hand git the token.

    The agent phase owned this checkout and its home without a credential,
    but it could still plant hooks in ``.git``, a ``core.hooksPath``, a
    credential helper in the repository config, and a global configuration
    in its home — all of which git would run or read on the next fetch,
    commit, and push. This container is the first process in the session to
    hold the push token, so the home is replaced and the repository
    metadata rebuilt *before* the token is introduced, and the askpass
    helper is installed only after that rebuild: a fresh, standard
    configuration is what the token meets, and nothing the agent planted
    can intercept it.

    Unlike preparation, the working tree itself is kept — it is the
    session's work. The branch is re-anchored on a fresh fetch of the base
    branch: the rebuild removed its ref, and a retried session must push a
    diff against the base, not build on a previous run's tip. The index is
    aligned with the branch without touching a single file.

    Returns False when there is no working copy to finalize: the agent left
    nothing, or a link in place of the checkout.
    """
    _reset_agent_home()
    if CHECKOUT.is_symlink() or (CHECKOUT.exists() and not CHECKOUT.is_dir()):
        log("the checkout is not a directory; there is no work to finalize")
        if CHECKOUT.is_symlink():
            CHECKOUT.unlink()
        return False
    if not (CHECKOUT / ".git").is_dir():
        # No repository at the checkout path: nothing to commit, and an
        # init here would only create an empty one the push would fill
        # with a history-less tree.
        log("no repository at the checkout; there is no work to finalize")
        return False
    _rebuild_git_metadata(repo_url)
    # Only now that the metadata is fresh and standard does the token enter
    # the process: askpass is the only credential git will see, and
    # nothing the agent planted can run before it is installed.
    _install_git_askpass(token)
    run(["git", "fetch", "--depth", "50", "origin", base_branch], cwd=CHECKOUT)
    # Re-anchor the session's branch on the base it was given (the rebuild
    # removed its ref, see above).
    run(["git", "update-ref", f"refs/heads/{branch}", "FETCH_HEAD"], cwd=CHECKOUT, quiet=True)
    # Track the remote branch when a previous run left one, so the
    # force-with-lease push below verifies against what is actually there.
    # A first run has none; the lease then requires the remote branch to be
    # absent, which it is.
    run(["git", "fetch", "--depth", "50", "origin", branch], cwd=CHECKOUT, check=False, quiet=True)
    run(["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=CHECKOUT, quiet=True)
    # Mixed reset: the index follows the branch, the working tree — the
    # agent's work — is left exactly as it stands.
    run(["git", "reset"], cwd=CHECKOUT, quiet=True)
    _configure_git_identity()
    return True


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


# What the CLI prints when its connection to the model died mid-answer. The
# runner causes exactly this on purpose: a session paused to give capacity
# back is frozen and taken off the model network, so the response it was
# reading ends under it. Every session that was paused died this way before
# the retry below existed, and every session that was never paused finished.
_INTERRUPTIONS = (
    "connection lost mid-response",
    "connection error",
    "api error: request timed out",
    "fetch failed",
    "socket hang up",
    "econnreset",
)

# How many times a run may be picked up again after such an interruption.
# The work itself is in the checkout, so continuing costs a prompt and the
# conversation it resumes; three is enough for a busy afternoon of pauses
# and few enough that a genuinely broken gateway stops being retried.
_MAX_CONTINUATIONS = 3


def _agent_command(prompt: str, *, resuming: bool) -> list[str]:
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
    if resuming:
        # Same conversation, same working directory: the agent keeps what it
        # has already read and done instead of starting the task again.
        cmd.append("--continue")
    max_turns = os.environ.get("LOGOS_SESSION_MAX_TURNS", "").strip()
    if max_turns.isdigit():
        cmd += ["--max-turns", max_turns]
    return cmd


def _drive_agent(cmd: list[str]) -> tuple[int, dict[str, object], bool]:
    """Run one invocation. Returns its exit code, usage, and whether it was cut off."""
    usage: dict[str, object] = {}
    interrupted = False
    process = subprocess.Popen(cmd, cwd=CHECKOUT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        if any(marker in line.lower() for marker in _INTERRUPTIONS):
            interrupted = True
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
    return process.wait(), usage, interrupted


def run_agent(task: str) -> dict[str, object]:
    """Drive the coding agent and return what it reported about the run.

    An interrupted run is picked up rather than failed. The platform takes
    its capacity back by freezing a session and cutting it off the model
    network — deliberately, so a waiting user gets the slot — and the agent
    finds a dead response when it thaws. Treating that as a failed session
    threw away everything it had done: hours of work, uncommitted, in a
    checkout the next session resets.
    """
    prompt = build_prompt(task)
    started = time.monotonic()
    log("starting agent")
    usage: dict[str, object] = {}
    for attempt in range(_MAX_CONTINUATIONS + 1):
        resuming = attempt > 0
        if resuming:
            log(f"the agent's connection was cut; continuing where it left off ({attempt}/{_MAX_CONTINUATIONS})")
        code, run_usage, interrupted = _drive_agent(
            _agent_command(CONTINUE_PROMPT if resuming else prompt, resuming=resuming)
        )
        if run_usage:
            usage = run_usage
        if code == 0:
            elapsed = time.monotonic() - started
            log(f"agent finished in {elapsed:.0f}s with exit code {code}")
            return usage
        if not interrupted or attempt == _MAX_CONTINUATIONS:
            elapsed = time.monotonic() - started
            log(f"agent finished in {elapsed:.0f}s with exit code {code}")
            raise RuntimeError(f"agent exited with code {code}")
    raise RuntimeError("agent exited without a result")


# What the agent is told when it comes back from an interruption. Short on
# purpose: the conversation it resumes carries the task, and repeating it
# would invite starting over.
CONTINUE_PROMPT = (
    "Your connection to the model was interrupted — the platform froze this "
    "session to give a waiting user its capacity, and the answer you were "
    "receiving was cut off. Nothing you had already done was lost: the "
    "working copy is exactly as you left it. Carry on from where you were. "
    "If you are unsure how far you got, check `git status` and the files you "
    "were editing before assuming anything."
)

# What has been spent so far, as the transcript goes. The runner reads these
# lines back out of the container's output: it is the only channel out of the
# sandbox, which holds no credential and reaches nothing but the model
# gateway. The totals in the result file at the end are the authority.
_spent = {"in": 0, "out": 0}


def _report_usage(message: dict) -> None:
    """Print what has been spent so far, when it changes.

    Both sides accumulate, because that is what the agent is charged for and
    what the result file reports at the end: a turn's input is billed as
    input even though most of it is the conversation being re-read. Taking
    the largest turn instead would read lower here than in the final total,
    and a number that jumps when the session ends is worse than no number.
    """
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return
    read = sum(
        value
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        if isinstance(value := usage.get(key), int)
    )
    written = usage.get("output_tokens")
    before = dict(_spent)
    _spent["in"] += read
    _spent["out"] += written if isinstance(written, int) else 0
    if _spent != before:
        print(f"[usage] in={_spent['in']} out={_spent['out']}", flush=True)


def _render_event(event: dict) -> None:
    """Turn one stream event into a readable transcript line."""
    kind = event.get("type")
    if kind == "assistant":
        message = (event.get("message") or {}) if isinstance(event.get("message"), dict) else {}
        for block in message.get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                print(block["text"].strip(), flush=True)
            elif block.get("type") == "tool_use":
                print(f"[tool] {block.get('name')}", flush=True)
        _report_usage(message)
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


def _ref_sha(*refs: str) -> str | None:
    """The commit a ref names, or None when none of them resolves.

    ``--verify`` makes git fail on a ref that is really a literal string
    rather than a name; ``--quiet`` keeps the failure silent, so a missing
    ref reads as ``None`` instead of an exception.
    """
    for ref in refs:
        process = run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=CHECKOUT, check=False, quiet=True)
        sha = process.stdout.strip()
        if process.returncode == 0 and sha:
            return sha
    return None


# Paths whose contents GitHub executes with the repository's own CI
# permissions and secrets.
_WORKFLOW_PREFIX = ".github/workflows/"


def _refuse_workflow_changes(files: list[str]) -> None:
    """Stop a push that would edit CI, unless the token may do it anyway.

    A push token without `workflow` scope is refused by GitHub the moment a
    commit touches `.github/workflows/`, which is exactly the boundary the
    two-token setup buys: the agent phase may change any part of the
    repository except the part that runs with the repository's secrets. When
    a deployment configures only one token, that token has the scope — and
    then this check is the boundary instead. Failing here is deliberate: the
    session loses its work, which is recoverable, rather than opening a pull
    request whose workflow file runs with CI credentials, which is not.
    """
    if os.environ.get("LOGOS_AGENT_WORKFLOW_CHANGES") == "allow":
        return
    offending = sorted(path for path in files if path.startswith(_WORKFLOW_PREFIX))
    if not offending:
        return
    raise RuntimeError(
        "the session changed CI workflow files ("
        + ", ".join(offending[:5])
        + "), which this runner's push token is not allowed to carry into the "
        "repository. Configure a separate LOGOS_AGENT_SESSION_GITHUB_TOKEN "
        "without 'workflow' scope so GitHub enforces this, or an explicitly "
        "workflow-enabled session token if agent sessions are meant to edit CI."
    )


def commit_and_push(branch: str, task: str) -> int:
    files = changed_files()
    if not files:
        log("agent produced no changes; nothing to commit")
        return 0
    _refuse_workflow_changes(files)

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


def run_prepare() -> None:
    """Trusted phase one: bring the working copy to a trusted state.

    Runs in a helper container with egress and the scoped push token —
    the agent phase has neither, so whatever the agent later finds under
    /workspace was created here, by fixed harness code.
    """
    repo_url = require_env("LOGOS_REPO_URL")
    base_branch = os.environ.get("LOGOS_SESSION_BASE_BRANCH", "main")
    branch = require_env("LOGOS_SESSION_BRANCH")
    token = os.environ.get("GITHUB_TOKEN", "")
    prepare_checkout(repo_url, base_branch, branch, token)


def run_agent_phase(result: Result) -> None:
    """Untrusted phase two: the coding agent works on the checkout.

    This container holds no reusable credential: model traffic goes only to
    the credential-injecting gateway (the token in the environment is a
    placeholder the gateway replaces), and the GitHub operations belong to
    the finalizer. So even an agent that is steered into exfiltrating its
    environment can exfiltrate nothing of value.
    """
    task = require_env("LOGOS_SESSION_TASK")
    require_env("LOGOS_SESSION_BRANCH")
    if not os.environ.get("ANTHROPIC_BASE_URL"):
        raise RuntimeError("no model endpoint provided; the agent has no model to call")

    usage = run_agent(task)

    tokens_in, tokens_out, cost = usage_totals(usage)
    result.data.update(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
    # Screenshots are the runner's job, taken after settlement: a
    # session's own view of the dev environment is stale the moment its
    # deploy is queued, and the runner is the one that knows when the
    # deploy has landed.
    log("agent finished; handing the checkout to the finalizer")


def run_finalize(result: Result) -> None:
    """Trusted phase three: the authenticated GitHub operations.

    The agent phase never held a GitHub token; this container gets the
    scoped one and egress, and is the only phase allowed to talk to GitHub
    with it. Before the token is introduced, the checkout and home are
    brought under trusted metadata again — the agent owned both while it
    ran — and the askpass helper is installed only after that rebuild, so
    ``git push`` authenticates with a credential nothing planted can
    intercept. It adds its outcome to the result file the agent phase
    wrote (tokens, cost) rather than replacing it.
    """
    branch = require_env("LOGOS_SESSION_BRANCH")
    task = require_env("LOGOS_SESSION_TASK")
    base_branch = os.environ.get("LOGOS_SESSION_BASE_BRANCH", "main")
    repo_url = require_env("LOGOS_REPO_URL")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        log("no GitHub token provided; leaving changes uncommitted in the workspace")
        return
    # Whose work this is about to become. Checked before anything is
    # committed or pushed, so a wrong token fails the session instead of
    # putting agent commits under a contributor's name.
    verify_token_identity(token)

    path = Path(os.environ.get("LOGOS_ARTIFACT_DIR", "/artifacts")) / "result.json"
    if path.is_file():
        try:
            result.data.update(json.loads(path.read_text()))
        except Exception as exc:
            log(f"ignoring unreadable result file from the agent phase: {exc}")

    count = commit_and_push(branch, task) if finalize_checkout(repo_url, base_branch, branch, token) else 0
    result.data["files_changed"] = count
    result.data["committed"] = count > 0
    if count and os.environ.get("LOGOS_SESSION_OPEN_PR") == "1":
        result.data["pr_url"] = open_pull_request(branch, base_branch, task)
    # The exact commit the runner must build: this run's own commit, or —
    # when the agent changed nothing this time — the tip the branch already
    # carries. The runner pins its build poll to it. The branch is not a
    # fresh ref: a retried session force-pushes a new commit onto it, and a
    # completed run of the earlier commit would otherwise still be "the
    # build of this branch".
    result.data["pushed_sha"] = _ref_sha("HEAD") if count else _ref_sha(f"refs/remotes/origin/{branch}", "HEAD")


def main() -> int:
    """Run whichever phase of the session this container was asked for.

    The runner runs ``prepare``, ``agent``, and ``finalize`` as separate
    containers: the two trusted phases carry credentials and egress, the
    untrusted agent phase carries neither.
    """
    phase = os.environ.get("LOGOS_SESSION_PHASE", "agent").strip().lower()
    result = Result()
    try:
        if phase == "prepare":
            run_prepare()
        elif phase == "finalize":
            run_finalize(result)
        else:
            run_agent_phase(result)
        log("phase complete")
        return 0
    except Exception as exc:
        fail(str(exc))
        result.data["error"] = str(exc)
        return 1
    finally:
        result.write()


if __name__ == "__main__":
    sys.exit(main())
