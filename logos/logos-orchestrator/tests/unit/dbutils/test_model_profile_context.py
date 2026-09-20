"""The historic context high-water mark of model_profiles.

The orchestrator's view of a model's context used to live only in the live
worker runtime snapshots: with every workernode offline, /v1/models carried
no context fields at all and the clients (claude-logos, OpenCode) sized the
session from a blind constant that is a guess for every model at once.
``derived_reported_context_length`` plus the ``max_reported_context_length``
column fix that: every worker snapshot persists the widest context the
profile reports, and the upsert keeps the maximum only, so a later, narrower
calibration cannot shrink the mark.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from logos.dbutils.dbmanager import DBManager, derived_reported_context_length


def _db():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    return db


# ---------------------------------------------------------------------------
# derived_reported_context_length
# ---------------------------------------------------------------------------


def test_non_dict_profile_reports_no_length():
    assert derived_reported_context_length(None) == 0
    assert derived_reported_context_length("qwen-27b") == 0
    assert derived_reported_context_length({}) == 0


def test_manual_override_is_the_length():
    assert derived_reported_context_length({"max_context_length": 131072}) == 131072


def test_calibrated_cap_counts_on_its_own():
    """A calibration cap counts as the reported context when it is the only
    available context value. When no wider KV point is recorded, that cap is the
    context the profile reports. Ignoring it is exactly what made the model
    look context-unknown while its worker sat connected and ready to serve
    it at that width."""
    assert derived_reported_context_length({"calibration_max_model_len": 49152}) == 49152


def test_widest_kv_sweep_point_wins():
    pairs = [
        {"kv_mb": 1024.0, "max_model_len": 33000},
        {"kv_mb": 8192.0, "max_model_len": 262144},
    ]
    assert derived_reported_context_length({"kv_cache_to_max_model_len_pairs": pairs}) == 262144


def test_maximum_across_all_three_sources():
    profile = {
        "max_context_length": 131072,
        "calibration_max_model_len": 98304,
        "kv_cache_to_max_model_len_pairs": [{"kv_mb": 4096.0, "max_model_len": 196608}],
    }
    assert derived_reported_context_length(profile) == 196608


def test_garbage_values_are_ignored():
    profile = {
        "max_context_length": None,
        "calibration_max_model_len": "not-a-number",
        "kv_cache_to_max_model_len_pairs": [
            {"kv_mb": 1024.0},
            "garbage",
            {"max_model_len": -5},
        ],
    }
    assert derived_reported_context_length(profile) == 0


# ---------------------------------------------------------------------------
# upsert_model_profiles — high-water mark
# ---------------------------------------------------------------------------


def test_upsert_derives_and_binds_the_reported_length():
    db = _db()
    db.upsert_model_profiles(
        7,
        {"gemma-12b": {"calibration_max_model_len": 24576, "residency_source": "calibrated"}},
    )

    assert db.session.execute.call_count == 1
    _sql, params = db.session.execute.call_args[0]
    assert params["max_reported_context_length"] == 24576
    # The conflict clause keeps the larger of stored and freshly derived, so a
    # later, narrower calibration cannot shrink the mark. The COALESCE is
    # required: rows written before the column existed hold NULL, and
    # GREATEST with a NULL argument returns NULL in Postgres. (Checked against
    # the source rather than the sqlalchemy object: the unit-test conftest
    # stubs sqlalchemy, so text() calls come back as None here.)
    source = inspect.getsource(DBManager.upsert_model_profiles)
    assert "GREATEST(" in source
    assert "COALESCE(model_profiles.max_reported_context_length, 0)" in source


def test_upsert_of_a_context_unknown_profile_binds_zero():
    db = _db()
    db.upsert_model_profiles(7, {"cloud-like": {"engine": "vllm"}})

    _, params = db.session.execute.call_args[0]
    assert params["max_reported_context_length"] == 0


# ---------------------------------------------------------------------------
# get_historic_max_context_by_model
# ---------------------------------------------------------------------------


def test_historic_max_reduces_each_model_across_providers():
    db = _db()
    db.session.execute.return_value = iter(
        [
            ("gemma-12b", 49152),
            ("qwen-27b", 262144),
        ]
    )

    assert db.get_historic_max_context_by_model() == {
        "gemma-12b": 49152,
        "qwen-27b": 262144,
    }


# ---------------------------------------------------------------------------
# get_catalog_context_by_model
# ---------------------------------------------------------------------------


def test_catalog_context_reduces_each_model_to_the_smallest_window():
    # A model can appear once per cloud provider it is associated with; like
    # every other source of a model's context, the smallest published window
    # is the only one that holds unconditionally.
    db = _db()
    db.session.execute.return_value = MagicMock(
        fetchall=MagicMock(
            return_value=[
                SimpleNamespace(name="gpt-5.6-luna", max_input_tokens=1050000),
                SimpleNamespace(name="gpt-5.6-luna", max_input_tokens=1000000),
                SimpleNamespace(name="gpt-5.6-terra", max_input_tokens=1050000),
            ]
        )
    )

    assert db.get_catalog_context_by_model() == {
        "gpt-5.6-luna": 1000000,
        "gpt-5.6-terra": 1050000,
    }


def test_catalog_context_drops_rows_without_a_positive_window():
    db = _db()
    db.session.execute.return_value = MagicMock(
        fetchall=MagicMock(
            return_value=[
                SimpleNamespace(name="windowless-model", max_input_tokens=None),
                SimpleNamespace(name="zero-model", max_input_tokens=0),
                SimpleNamespace(name="fine-model", max_input_tokens=131072),
            ]
        )
    )

    assert db.get_catalog_context_by_model() == {"fine-model": 131072}


def test_catalog_context_query_only_reads_cloud_associated_models():
    # The catalog figure stands in for what a provider serves, so it must not
    # be read for a model only a logosnode provider serves: a local-only model
    # with no lane up has no window being served, and advertising the
    # registry's number for it would report one no deployment holds. (Checked
    # against the source rather than the executed text: the unit-test conftest
    # stubs sqlalchemy, so text() calls come back as None here.)
    source = inspect.getsource(DBManager.get_catalog_context_by_model)
    assert "JOIN model_provider mp ON mp.model_id = m.id" in source
    assert "JOIN providers p ON p.id = mp.provider_id" in source
    assert "p.provider_type = 'cloud'" in source
