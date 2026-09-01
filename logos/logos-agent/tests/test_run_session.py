"""What a session may carry over from a previous session in the same workspace.

A session runs with permission prompts disabled and a push token in its
environment, so it can write hooks, git configuration, and dotfiles anywhere
in the workspace. The next session is credential-bearing too, so none of
that may survive: the planted ``pre-commit`` hook must not run, a planted
``core.hooksPath`` must not be visible to git, and the agent's home — where
a ``.gitconfig`` or a ``.claude/settings.json`` with hooks would live — must
be replaced, not reused.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workspace"))

from run_session import _rebuild_git_metadata, _reset_agent_home  # noqa: E402

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
    config = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=checkout, text=True, capture_output=True)
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
