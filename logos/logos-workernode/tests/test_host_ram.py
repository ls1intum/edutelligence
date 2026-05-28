"""Tests for the worker-side host-RAM measurement helpers."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import patch

import pytest

from logos_worker_node import host_ram


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="/proc/<pid>/smaps_rollup and /proc/<pid>/status are Linux-only",
)
def test_read_process_rss_returns_positive_for_self():
    """The current Python process has a non-zero RSS via /proc/self/status."""
    pid = os.getpid()
    mb = host_ram.read_process_rss_mb(pid)
    assert mb > 0


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="/proc is Linux-only",
)
def test_walk_process_tree_includes_root_pid():
    pid = os.getpid()
    tree = host_ram.walk_process_tree(pid)
    assert pid in tree


def test_read_process_pss_returns_zero_for_missing_pid():
    # PID 0 never has a /proc entry; PSS read must fail-soft to 0.0
    assert host_ram.read_process_pss_mb(0) == 0.0


def test_read_process_rss_returns_zero_for_missing_pid():
    assert host_ram.read_process_rss_mb(0) == 0.0


def test_walk_process_tree_handles_dead_pid():
    """A non-existent pid yields an empty tree (not a crash)."""
    assert host_ram.walk_process_tree(2**30) == set()


def test_measure_process_tree_falls_back_to_rss_when_pss_unavailable():
    """If smaps_rollup is empty/unreadable, fall back to RSS-summing the tree."""
    fake_pid = 12345
    with (
        patch.object(host_ram, "walk_process_tree", return_value={fake_pid, 12346}),
        patch.object(host_ram, "read_process_pss_mb", return_value=0.0),
        patch.object(host_ram, "read_process_rss_mb", side_effect=[500.0, 250.0]),
    ):
        mb, source = host_ram.measure_process_tree_host_ram_mb(fake_pid)
    assert source == "rss"
    assert mb == pytest.approx(750.0)


def test_measure_process_tree_prefers_pss_when_available():
    """When PSS readings exist, they are preferred over RSS to avoid TP double-count."""
    fake_pid = 12345
    with (
        patch.object(host_ram, "walk_process_tree", return_value={fake_pid, 12346}),
        patch.object(host_ram, "read_process_pss_mb", side_effect=[600.0, 300.0]),
        patch.object(host_ram, "read_process_rss_mb", side_effect=[5000.0, 4900.0]),
    ):
        mb, source = host_ram.measure_process_tree_host_ram_mb(fake_pid)
    assert source == "pss"
    assert mb == pytest.approx(900.0)


def test_measure_process_tree_unknown_for_dead_root():
    mb, source = host_ram.measure_process_tree_host_ram_mb(2**30)
    assert mb == 0.0
    assert source == "unknown"
