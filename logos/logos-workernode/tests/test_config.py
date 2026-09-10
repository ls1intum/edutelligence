"""Credential (.env) loading in the config loader.

The .env next to config.yml carries LOGOS_URL / LOGOS_API_KEY. On the
compose (CUDA) path docker-compose reads that file itself; a natively
running worker (the macOS/MLX path) relies on the loader in config.py.
Real environment variables always win over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from logos_worker_node import config as worker_config


@pytest.fixture
def install_root(tmp_path, monkeypatch):
    """A fake install root: config.yml + .env, addressed via
    LOGOS_WORKER_NODE_CONFIG exactly like the launchd agent does."""
    root = tmp_path / "install"
    root.mkdir()
    (root / "config.yml").write_text("worker:\n  name: test-node\n")
    (root / ".env").write_text(
        "# credentials\n"
        "LOGOS_URL=https://logos.example\n"
        'LOGOS_API_KEY="quoted-key"\n'
        "\n"
        "SOME_EXTRA_VAR=plain\n"
    )
    monkeypatch.setenv("LOGOS_WORKER_NODE_CONFIG", str(root / "config.yml"))
    for var in ("LOGOS_URL", "LOGOS_API_KEY", "SOME_EXTRA_VAR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(worker_config, "_config", None, raising=False)
    return root


def test_env_file_next_to_config_is_loaded(install_root: Path) -> None:
    cfg = worker_config.load_config()
    assert cfg.logos.enabled is True
    assert cfg.logos.logos_url == "https://logos.example"
    assert cfg.logos.shared_key == "quoted-key"
    assert os.environ["SOME_EXTRA_VAR"] == "plain"


def test_real_env_var_wins_over_env_file(install_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_URL", "https://explicit.example")
    cfg = worker_config.load_config()
    assert cfg.logos.logos_url == "https://explicit.example"


def test_missing_env_file_is_a_noop(install_root: Path) -> None:
    (install_root / ".env").unlink()
    cfg = worker_config.load_config()
    assert cfg.logos.enabled is False
    assert cfg.logos.logos_url == ""


def test_env_file_resolves_from_cwd_without_config_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LOGOS_WORKER_NODE_CONFIG", raising=False)
    monkeypatch.delenv("LOGOS_URL", raising=False)
    monkeypatch.setattr(worker_config, "_config", None, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yml").write_text("worker:\n  name: cwd-node\n")
    (tmp_path / ".env").write_text("LOGOS_URL=https://cwd.example\n")

    cfg = worker_config.load_config()
    assert cfg.logos.logos_url == "https://cwd.example"
