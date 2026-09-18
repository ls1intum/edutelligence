"""Tests for resolve_proxy_model_from_deployments (#980 O17).

The in-memory twin of DBManager.resolve_proxy_model for non-admin keys: it
must resolve exactly the names the SQL non-admin branch resolves, over the
deployment rows get_deployments_for_api_key already fetched in the same
session. The name-matching tiers (exact / alias / planner-alias / replica
suffix) are covered by test_resolve_requested_model_name.py; here the rows
carry deployment-shaped keys, and the interesting cases are the row-set
handling: dedup over multiple providers, the Model {id} name fallback, and
tolerance of malformed rows.
"""

from logos.logosnode_snapshot import resolve_proxy_model_from_deployments


def _deployment(model_id: int, model_name: str, aliases=None, provider_id: int = 1) -> dict:
    return {
        "model_id": model_id,
        "provider_id": provider_id,
        "model_name": model_name,
        "aliases": aliases,
    }


def test_exact_canonical_name_resolves():
    deployments = [_deployment(11, "llama-3")]
    assert resolve_proxy_model_from_deployments(deployments, "llama-3") == (11, "llama-3")


def test_stored_alias_resolves_to_canonical_name():
    deployments = [_deployment(11, "llama-3", aliases="fast-llama")]
    assert resolve_proxy_model_from_deployments(deployments, "fast-llama") == (11, "llama-3")


def test_planner_alias_and_replica_suffix_forms_resolve():
    deployments = [_deployment(11, "llama")]
    assert resolve_proxy_model_from_deployments(deployments, "planner-llama") == (11, "llama")
    assert resolve_proxy_model_from_deployments(deployments, "planner-llama-2") == (11, "llama")


def test_alias_ambiguity_is_refused():
    # The SQL resolver refuses a name matching two candidates; the in-memory
    # twin must not guess either.
    deployments = [
        _deployment(1, "llama/2", provider_id=1),
        _deployment(2, "llama:2", provider_id=2),
    ]
    assert resolve_proxy_model_from_deployments(deployments, "planner-llama_2") is None


def test_null_model_name_falls_back_to_model_id_name():
    # m.name is NULL: both the SQL branch and this helper see "Model {id}".
    deployments = [_deployment(42, None)]
    assert resolve_proxy_model_from_deployments(deployments, "Model 42") == (42, "Model 42")


def test_multi_provider_rows_dedup_to_one_candidate():
    # A model linked to two permitted providers yields two deployment rows;
    # the candidates list must still be unambiguous.
    deployments = [
        _deployment(11, "llama-3", provider_id=1),
        _deployment(11, "llama-3", provider_id=2),
    ]
    assert resolve_proxy_model_from_deployments(deployments, "llama-3") == (11, "llama-3")
    assert resolve_proxy_model_from_deployments(deployments, "planner-llama-3") == (11, "llama-3")


def test_model_ids_are_deduped_in_provider_order():
    # ORDER BY model_id, provider_id: the first row of a model is the one
    # kept, so aliases come from the first provider row only.
    deployments = [
        _deployment(1, "llama", aliases="a1", provider_id=1),
        _deployment(1, "llama", aliases="a2", provider_id=2),
    ]
    assert resolve_proxy_model_from_deployments(deployments, "a1") == (1, "llama")
    assert resolve_proxy_model_from_deployments(deployments, "a2") is None


def test_malformed_rows_are_ignored():
    deployments = [
        "not-a-dict",  # type: ignore[list-item]
        {"provider_id": 2},  # no model_id
        {"model_id": None, "model_name": "ghost"},
        _deployment(11, "llama-3"),
    ]
    assert resolve_proxy_model_from_deployments(deployments, "llama-3") == (11, "llama-3")


def test_empty_and_none_deployments_resolve_to_none():
    assert resolve_proxy_model_from_deployments([], "llama") is None
    assert resolve_proxy_model_from_deployments(None, "llama") is None


def test_unresolvable_name_resolves_to_none():
    deployments = [_deployment(11, "llama-3")]
    assert resolve_proxy_model_from_deployments(deployments, "gemma") is None
    assert resolve_proxy_model_from_deployments(deployments, "") is None


def test_special_character_normalization_matches_sql_path():
    # org/model:tag is addressable as org_model_tag (and its planner form),
    # exactly like the SQL resolver via the shared _resolve_requested_model_name.
    deployments = [_deployment(11, "org/model:tag")]
    assert resolve_proxy_model_from_deployments(deployments, "org_model_tag") == (11, "org/model:tag")
    assert resolve_proxy_model_from_deployments(deployments, "planner-org_model_tag") == (11, "org/model:tag")
