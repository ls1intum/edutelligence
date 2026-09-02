"""What a session may carry over from a previous session in the same workspace.

A session runs with permission prompts disabled and a push token in its
environment, so it can write hooks, git configuration, and dotfiles anywhere
in the workspace. The next session is credential-bearing too, so none of
that may survive: the planted ``pre-commit`` hook must not run, a planted
``core.hooksPath`` must not be visible to git, and the agent's home — where
a ``.gitconfig`` or a ``.claude/settings.json`` with hooks would live — must
be replaced, not reused.

The same boundary applies between the untrusted agent phase and the trusted
finalizer of the *same* session: the finalizer is the first process in the
session to hold the push token, so it must rebuild the checkout's metadata
and the home before it installs the credential, or an agent-planted hook or
credential helper would run with that token in its environment.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workspace"))

from run_session import (  # noqa: E402
    Result,
    _clear_checkout,
    _rebuild_git_metadata,
    _reset_agent_home,
    commit_and_push,
    finalize_checkout,
    run_finalize,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

REPO_URL = "https://github.com/ls1intum/edutelligence.git"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def _plant_previous_session(workspace: Path) -> tuple[Path, Path]:
    """A checkout plus home as a hostile previous session leaves them.

    Returns (checkout, home). The repository has one real commit (so the
    object store is non-empty), and the plants are: an executable pre-commit
    hook in .git/hooks, a core.hooksPath in the repository config pointing
    at a second planted hook, and a global .gitconfig plus .claude hooks in
    the home.
    """
    checkout = workspace / "repo"
    home = workspace / ".home"
    (checkout / ".git").mkdir(parents=True)
    home.mkdir(parents=True)

    _git("init", "--quiet", cwd=checkout)
    _git("config", "user.name", "previous agent", cwd=checkout)
    _git("config", "user.email", "previous@example.com", cwd=checkout)
    (checkout / "file.txt").write_text("work of the previous session\n")
    _git("add", "file.txt", cwd=checkout)
    _git("commit", "--quiet", "-m", "previous session", cwd=checkout)

    # A bypass-permissions session installing a hook that runs on the next
    # session's first commit, with that session's token in the environment.
    marker = workspace / "hook-ran"
    hook = checkout / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)

    # ...and one more, out of the way, behind a planted core.hooksPath.
    planted_hooks = checkout / ".git" / "evil-hooks"
    planted_hooks.mkdir()
    (planted_hooks / "pre-commit").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (planted_hooks / "pre-commit").chmod(0o755)
    _git("config", "core.hooksPath", ".git/evil-hooks", cwd=checkout)

    # The home carries a global hooksPath and the CLI's own hook settings.
    (home / ".gitconfig").write_text("[core]\n\thooksPath = /tmp/evil-global-hooks\n")
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text('{"hooks": {}}')
    return checkout, home


def _patch_workspace(monkeypatch, workspace: Path) -> None:
    import run_session

    monkeypatch.setattr(run_session, "WORKSPACE", workspace)
    monkeypatch.setattr(run_session, "CHECKOUT", workspace / "repo")
    monkeypatch.setenv("HOME", str(workspace / ".home"))
    # These tests push to a bare repository on disk, so there is no GitHub
    # account behind the token to resolve. The check itself is covered by
    # TestPushIdentity below, against a stubbed `gh`.
    monkeypatch.setattr(run_session, "verify_token_identity", lambda _token: None)


def test_planted_git_metadata_does_not_survive_the_rebuild(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    checkout, _ = _plant_previous_session(workspace)
    marker = workspace / "hook-ran"
    _patch_workspace(monkeypatch, workspace)
    objects_before = sorted(
        p.relative_to(checkout / ".git" / "objects") for p in (checkout / ".git" / "objects").rglob("*") if p.is_file()
    )

    _reset_agent_home()
    _rebuild_git_metadata(REPO_URL)

    # The planted hooks are gone: nothing to execute from the repository
    # metadata, and the config that pointed at them no longer exists.
    assert not (checkout / ".git" / "hooks" / "pre-commit").exists()
    assert not (checkout / ".git" / "evil-hooks").exists()
    # --local: the machine's system git config is out of scope for the
    # rebuild; what must be gone is what the previous session planted in
    # the repository itself.
    config = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"], cwd=checkout, text=True, capture_output=True
    )
    assert config.returncode != 0, "core.hooksPath survived the rebuild"

    # The object store is the one part that is kept: the previous commit's
    # objects are still there, nothing was re-cloned.
    objects_after = sorted(
        p.relative_to(checkout / ".git" / "objects") for p in (checkout / ".git" / "objects").rglob("*") if p.is_file()
    )
    assert objects_before and objects_before == objects_after

    # A commit in the rebuilt repository runs no planted hook.
    _git("config", "user.name", "Logos Agent", cwd=checkout)
    _git("config", "user.email", "logos-agent@users.noreply.github.com", cwd=checkout)
    _git("commit", "--quiet", "--allow-empty", "-m", "next session", cwd=checkout)
    assert not marker.exists()

    # The remote is re-established from the trusted URL the harness was
    # given, not from whatever the previous session set.
    origin = _git("remote", "get-url", "origin", cwd=checkout).stdout.strip()
    assert origin == REPO_URL


def test_the_agent_home_is_replaced_not_reused(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    _, home = _plant_previous_session(workspace)
    _patch_workspace(monkeypatch, workspace)

    _reset_agent_home()

    # A fresh, empty home: the global hooksPath, the CLI settings, and any
    # poisoned tool caches a previous session wrote are all gone.
    assert home.is_dir()
    assert list(home.iterdir()) == []


def test_a_home_left_as_a_symlink_is_replaced_too(tmp_path, monkeypatch):
    # A previous session could have turned HOME into a symlink pointing at
    # files outside the workspace; following it with rmtree would delete
    # those, and keeping it would reuse them. Both are wrong: unlink, then
    # create a real directory.
    workspace = tmp_path / "ws"
    (workspace / "repo").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".gitconfig").write_text("[core]\n\thooksPath = /tmp/evil\n")
    home = workspace / ".home"
    home.symlink_to(outside)
    _patch_workspace(monkeypatch, workspace)

    _reset_agent_home()

    assert home.is_dir() and not home.is_symlink()
    assert list(home.iterdir()) == []
    # Whatever the symlink pointed at is untouched: we never followed it.
    assert (outside / ".gitconfig").exists()


def test_a_dangling_home_symlink_is_removed_not_kept(tmp_path, monkeypatch):
    # `exists()` follows the link, so a dangling one is invisible to it —
    # but `mkdir` would fail on the surviving path and the next session
    # would break the same way. The link must go whether or not its target
    # exists.
    workspace = tmp_path / "ws"
    (workspace / "repo").mkdir(parents=True)
    home = workspace / ".home"
    home.symlink_to(tmp_path / "a-target-that-was-never-created")
    assert home.is_symlink()
    assert not home.exists()
    _patch_workspace(monkeypatch, workspace)

    _reset_agent_home()

    assert home.is_dir() and not home.is_symlink()
    assert list(home.iterdir()) == []


def test_a_dangling_checkout_symlink_is_removed_before_the_clone(tmp_path, monkeypatch):
    # One session turning /workspace/repo into a dangling link must not make
    # every later session in the workspace fail at the clone: the link is
    # gone before git runs, whether or not its target exists.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    checkout = workspace / "repo"
    checkout.symlink_to(tmp_path / "a-target-that-was-never-created")
    assert checkout.is_symlink()
    assert not checkout.exists()
    _patch_workspace(monkeypatch, workspace)

    _clear_checkout()

    assert not checkout.exists() and not checkout.is_symlink()


def _make_origin(workspace: Path) -> Path:
    """A bare repository with one commit on ``main``, standing in for the
    trusted remote the finalizer pushes to."""
    seed = workspace / "seed"
    seed.mkdir()
    _git("init", "--quiet", "--initial-branch=main", cwd=seed)
    _git("config", "user.name", "base", cwd=seed)
    _git("config", "user.email", "base@example.com", cwd=seed)
    (seed / "app.py").write_text("print('base')\n")
    _git("add", "app.py", cwd=seed)
    _git("commit", "--quiet", "-m", "base", cwd=seed)
    origin = workspace / "origin.git"
    subprocess.run(["git", "clone", "--quiet", "--bare", str(seed), str(origin)], check=True)
    return origin


def _plant_agent_phase(workspace: Path, origin: Path, branch: str) -> tuple[Path, Path, Path]:
    """A checkout plus home as a hostile agent phase leaves them.

    The checkout is on the session's branch with one change in the working
    tree, and the plants are: an executable pre-commit hook in .git/hooks,
    a second planted hook behind a repository-config ``core.hooksPath``, a
    credential helper in the repository config, and a global ``.gitconfig``
    in the home. Every one of them would run or be read by git during the
    finalizer's fetch, commit, and push — with the push token in the
    environment.

    Returns (checkout, home, marker).
    """
    checkout = workspace / "repo"
    home = workspace / ".home"
    _git("clone", "--quiet", str(origin), str(checkout), cwd=workspace)
    home.mkdir(parents=True)
    _git("checkout", "-qb", branch, cwd=checkout)
    (checkout / "app.py").write_text("print('agent change')\n")

    marker = workspace / "finalizer-plant-ran"

    hook = checkout / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)

    planted_hooks = checkout / ".git" / "planted-hooks"
    planted_hooks.mkdir()
    (planted_hooks / "pre-commit").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (planted_hooks / "pre-commit").chmod(0o755)
    _git("config", "core.hooksPath", ".git/planted-hooks", cwd=checkout)

    helper = workspace / "credential-exfil.sh"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\n")
    helper.chmod(0o755)
    _git("config", "credential.helper", str(helper), cwd=checkout)

    (home / ".gitconfig").write_text("[core]\n\thooksPath = /tmp/evil-finalize-hooks\n")
    return checkout, home, marker


class TestFinalizer:
    """The trusted post-agent phase, against the agent-planted metadata.

    The finalizer container is fresh: nothing the prepare phase installed
    (the askpass helper above all) survives it. And the working copy it
    inherits was owned by the untrusted agent phase. So it must rebuild the
    metadata and the home before any git operation, and only then introduce
    the token.
    """

    BRANCH = "logos-agent/ws/session-9"

    def test_the_finalizer_rebuilds_metadata_and_pushes_the_work(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        origin = _make_origin(workspace)
        checkout, home, marker = _plant_agent_phase(workspace, origin, self.BRANCH)
        _patch_workspace(monkeypatch, workspace)

        assert finalize_checkout(f"file://{origin}", "main", self.BRANCH, "ghp-test-token") is True

        # The home and the repository metadata are trusted again: nothing
        # planted survives to run or be read. (--local: the machine's system
        # git config is out of scope for the rebuild.)
        assert list(home.iterdir()) == []
        for key in ("core.hooksPath", "credential.helper"):
            result = subprocess.run(
                ["git", "config", "--local", "--get", key], cwd=checkout, text=True, capture_output=True
            )
            assert result.returncode != 0, f"{key} survived the finalizer's rebuild"
        assert not (checkout / ".git" / "hooks" / "pre-commit").exists()
        assert not (checkout / ".git" / "planted-hooks").exists()

        # The token entered the process through the askpass helper, and only
        # after the rebuild: nothing on disk carries it, git is told to fail
        # fast instead of prompting, and the helper is the right mode.
        helper_path = os.environ.get("GIT_ASKPASS", "")
        assert helper_path, "GIT_ASKPASS is not installed"
        helper_file = Path(helper_path)
        assert "$GITHUB_TOKEN" in helper_file.read_text()
        assert stat.S_IMODE(helper_file.stat().st_mode) == 0o700
        assert os.environ["GIT_TERMINAL_PROMPT"] == "0"

        # The branch is re-anchored on the base, the working tree — the
        # agent's work — left exactly as it stands.
        head_branch = _git("symbolic-ref", "--short", "HEAD", cwd=checkout).stdout.strip()
        assert head_branch == self.BRANCH
        assert "app.py" in _git("status", "--porcelain", cwd=checkout).stdout

        # The push reaches the remote with exactly the agent's diff, on top
        # of the base — and nothing planted ran on the way.
        assert commit_and_push(self.BRANCH, "a long enough task description") == 1
        remote_file = _git("--git-dir", str(origin), "show", f"{self.BRANCH}:app.py", cwd=workspace).stdout
        assert remote_file == "print('agent change')\n"
        remote_subject = _git(
            "--git-dir", str(origin), "log", "--format=%s", "-1", self.BRANCH, cwd=workspace
        ).stdout.strip()
        assert remote_subject.startswith("`Logos`: ")
        parent = _git("--git-dir", str(origin), "rev-parse", f"{self.BRANCH}^", cwd=workspace).stdout.strip()
        base = _git("--git-dir", str(origin), "rev-parse", "main", cwd=workspace).stdout.strip()
        assert parent == base
        assert not marker.exists(), "a planted hook or credential helper ran in the finalizer"

    def test_a_retried_session_pushes_against_the_base_not_the_previous_tip(self, tmp_path, monkeypatch):
        # The remote branch exists from an earlier run of the same session.
        # Re-finalizing must not build on that tip: the diff belongs to the
        # base, and the force-with-lease push must verify against the tip it
        # just fetched, not blind over it.
        workspace = tmp_path / "ws"
        workspace.mkdir()
        origin = _make_origin(workspace)
        checkout, home, marker = _plant_agent_phase(workspace, origin, self.BRANCH)
        _patch_workspace(monkeypatch, workspace)

        assert finalize_checkout(f"file://{origin}", "main", self.BRANCH, "ghp-test-token") is True
        commit_and_push(self.BRANCH, "a long enough task description")

        # A second run of the session: new work in the same working copy.
        (checkout / "app.py").write_text("print('second run')\n")
        assert finalize_checkout(f"file://{origin}", "main", self.BRANCH, "ghp-test-token") is True
        assert commit_and_push(self.BRANCH, "a long enough task description") == 1

        # Two commits on the remote branch, and the second one sits on the
        # base — the first run's tip is gone, not a parent.
        log = _git("--git-dir", str(origin), "log", "--format=%s", self.BRANCH, cwd=workspace).stdout.splitlines()
        assert len(log) == 2 and log[1] == "base"
        remote_file = _git("--git-dir", str(origin), "show", f"{self.BRANCH}:app.py", cwd=workspace).stdout
        assert remote_file == "print('second run')\n"
        assert not marker.exists()

    @staticmethod
    def _patch_finalize_env(monkeypatch, tmp_path: Path, repo_url: str, branch: str) -> None:
        monkeypatch.setenv("LOGOS_SESSION_BRANCH", branch)
        monkeypatch.setenv("LOGOS_SESSION_TASK", "a long enough task description")
        monkeypatch.setenv("LOGOS_REPO_URL", repo_url)
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test-token")
        monkeypatch.setenv("LOGOS_ARTIFACT_DIR", str(tmp_path / "artifacts"))
        monkeypatch.setenv("LOGOS_SESSION_OPEN_PR", "0")

    def test_the_finalizer_records_the_commit_it_pushed(self, tmp_path, monkeypatch):
        # The runner pins its build poll to this sha: it is the exact commit
        # the push put on the remote branch, neither the branch name alone
        # nor the base the branch was re-anchored on.
        workspace = tmp_path / "ws"
        workspace.mkdir()
        origin = _make_origin(workspace)
        checkout, home, marker = _plant_agent_phase(workspace, origin, self.BRANCH)
        _patch_workspace(monkeypatch, workspace)
        self._patch_finalize_env(monkeypatch, tmp_path, f"file://{origin}", self.BRANCH)

        result = Result()
        run_finalize(result)

        assert result.data["committed"] is True
        assert result.data["files_changed"] == 1
        head = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
        tip = _git("--git-dir", str(origin), "rev-parse", self.BRANCH, cwd=workspace).stdout.strip()
        assert result.data["pushed_sha"] == head == tip

    def test_a_retried_run_without_new_work_pins_the_branch_tip(self, tmp_path, monkeypatch):
        # A retried run in which the agent changed nothing: no commit is
        # made this time, but the branch still carries the work of the first
        # run — and that is the commit the runner has to build, not the base
        # the re-anchored head now points at.
        workspace = tmp_path / "ws"
        workspace.mkdir()
        origin = _make_origin(workspace)
        checkout, home, marker = _plant_agent_phase(workspace, origin, self.BRANCH)
        _patch_workspace(monkeypatch, workspace)
        self._patch_finalize_env(monkeypatch, tmp_path, f"file://{origin}", self.BRANCH)

        first = Result()
        run_finalize(first)
        assert first.data["committed"] is True

        # Second run: the working copy goes back to the base content, so
        # there is nothing to commit — the remote branch keeps the first
        # run's commit. (The rebuild wiped the local main ref, so the base
        # is fetched fresh into FETCH_HEAD.)
        _git("fetch", "--quiet", "origin", "main", cwd=checkout)
        _git("checkout", "FETCH_HEAD", "--", ".", cwd=checkout)
        second = Result()
        run_finalize(second)

        assert second.data["committed"] is False
        assert second.data["files_changed"] == 0
        base = _git("--git-dir", str(origin), "rev-parse", "main", cwd=workspace).stdout.strip()
        tip = _git("--git-dir", str(origin), "rev-parse", self.BRANCH, cwd=workspace).stdout.strip()
        assert tip != base
        assert second.data["pushed_sha"] == tip

    def test_a_checkout_replaced_by_a_link_has_no_work_to_finalize(self, tmp_path, monkeypatch):
        # The agent may have turned the checkout itself into a link: the
        # finalizer must not commit, push, or even read through it into
        # another tree.
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside"
        (outside / "repo").mkdir(parents=True)
        (outside / "repo" / "not-session-work.txt").write_text("another tree")
        (workspace / "repo").symlink_to(outside / "repo")
        _patch_workspace(monkeypatch, workspace)

        assert finalize_checkout("file:///unused", "main", self.BRANCH, "ghp-test-token") is False

        # The link is gone, the target untouched: nothing was committed
        # against another tree.
        assert not (workspace / "repo").is_symlink()
        assert (outside / "repo" / "not-session-work.txt").exists()

    def test_a_git_directory_left_as_a_symlink_is_unlinked_not_followed(self, tmp_path, monkeypatch):
        # A session can point the checkout's .git at another repository's:
        # following it would delete and reinitialise the target's metadata.
        workspace = tmp_path / "ws"
        other = workspace / "other"
        (other / ".git").mkdir(parents=True)
        _git("init", "--quiet", cwd=other)
        _git("config", "user.name", "other repo", cwd=other)
        _git("config", "user.email", "other@example.com", cwd=other)
        (other / "a.txt").write_text("other repo content\n")
        _git("add", "a.txt", cwd=other)
        _git("commit", "--quiet", "-m", "other", cwd=other)
        checkout = workspace / "repo"
        checkout.mkdir(parents=True)
        (checkout / "work.txt").write_text("session work\n")
        (checkout / ".git").symlink_to(other / ".git")
        _patch_workspace(monkeypatch, workspace)

        _rebuild_git_metadata(REPO_URL)

        # The link is gone, the target's metadata intact, and a fresh real
        # .git with the trusted remote stands in its place.
        assert not (checkout / ".git").is_symlink()
        assert (checkout / ".git").is_dir()
        assert (checkout / ".git" / "hooks").is_dir()
        assert (other / ".git" / "config").is_file()
        assert _git("config", "--get", "user.name", cwd=other).stdout.strip() == "other repo"
        assert _git("config", "--get", "remote.origin.url", cwd=checkout).stdout.strip() == REPO_URL


class TestPushIdentity:
    """The finalizer pushes as the agent account or not at all.

    The runner checks the token at startup, but the container is where the
    push happens and where a rotated or swapped token would show up. A
    token belonging to a person must not put agent commits under that
    person's name.
    """

    @staticmethod
    def _stub_gh(monkeypatch, *, login: str = "LogosOSSAgent", returncode: int = 0, stderr: str = ""):
        import run_session

        calls: list = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, returncode, stdout=login + "\n", stderr=stderr)

        monkeypatch.setattr(run_session.subprocess, "run", fake_run)
        return calls

    def test_the_agent_account_is_accepted(self, monkeypatch):
        import run_session

        monkeypatch.delenv("LOGOS_AGENT_GITHUB_LOGIN", raising=False)
        calls = self._stub_gh(monkeypatch)

        run_session.verify_token_identity("ghp-token")

        # The token is passed to gh through the environment, never on the
        # command line where it would land in a process listing.
        cmd, kwargs = calls[0]
        assert cmd[:3] == ["gh", "api", "user"]
        assert kwargs["env"]["GH_TOKEN"] == "ghp-token"
        assert "ghp-token" not in " ".join(cmd)

    def test_a_configured_account_is_honoured(self, monkeypatch):
        import run_session

        monkeypatch.setenv("LOGOS_AGENT_GITHUB_LOGIN", "SomeOtherBot")
        self._stub_gh(monkeypatch, login="SomeOtherBot")

        run_session.verify_token_identity("ghp-token")

    def test_a_human_token_is_refused(self, monkeypatch):
        import run_session

        monkeypatch.delenv("LOGOS_AGENT_GITHUB_LOGIN", raising=False)
        self._stub_gh(monkeypatch, login="wasnertobias")

        with pytest.raises(RuntimeError, match="not as the agent account"):
            run_session.verify_token_identity("ghp-token")

    def test_an_unresolvable_token_is_refused(self, monkeypatch):
        import run_session

        monkeypatch.delenv("LOGOS_AGENT_GITHUB_LOGIN", raising=False)
        self._stub_gh(monkeypatch, returncode=1, stderr="gh: Bad credentials (HTTP 401)")

        with pytest.raises(RuntimeError, match="could not establish the identity"):
            run_session.verify_token_identity("ghp-token")

    def test_the_comparison_ignores_case(self, monkeypatch):
        import run_session

        monkeypatch.setenv("LOGOS_AGENT_GITHUB_LOGIN", "logosossagent")
        self._stub_gh(monkeypatch, login="LogosOSSAgent")

        run_session.verify_token_identity("ghp-token")


class TestWorkflowFileGuard:
    """CI files are the one thing a one-token deployment may not push.

    A workflow file the agent wrote runs with the repository's secrets as
    soon as its pull request opens. With a separate session token GitHub
    refuses such a push outright; when the runner's own token is used
    instead, that scope is present and the finalizer is the boundary.
    """

    def test_ordinary_changes_pass(self, monkeypatch):
        import run_session

        monkeypatch.setenv("LOGOS_AGENT_WORKFLOW_CHANGES", "deny")
        run_session._refuse_workflow_changes(["logos/logos-agent/app/main.py", "README.md"])

    def test_a_workflow_file_is_refused(self, monkeypatch):
        import run_session

        monkeypatch.setenv("LOGOS_AGENT_WORKFLOW_CHANGES", "deny")
        with pytest.raises(RuntimeError, match="CI workflow files"):
            run_session._refuse_workflow_changes([".github/workflows/logos_test.yml"])

    def test_a_scoped_session_token_may_change_them(self, monkeypatch):
        import run_session

        monkeypatch.setenv("LOGOS_AGENT_WORKFLOW_CHANGES", "allow")
        run_session._refuse_workflow_changes([".github/workflows/logos_test.yml"])

    def test_the_default_is_to_refuse(self, monkeypatch):
        # An unset variable means an older runner, or one that could not
        # decide: the safe answer is the restrictive one.
        import run_session

        monkeypatch.delenv("LOGOS_AGENT_WORKFLOW_CHANGES", raising=False)
        with pytest.raises(RuntimeError):
            run_session._refuse_workflow_changes([".github/workflows/x.yml"])
