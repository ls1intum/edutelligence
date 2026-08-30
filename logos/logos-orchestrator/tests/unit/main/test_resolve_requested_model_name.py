"""Tests for _resolve_requested_model_name.

Covers the planner-alias and replica-suffix resolution tiers, including the
numeric-suffix family collision (llama + llama-3) that made
planner-llama-3 unresolvable while both were deployed.
"""

import logos as main


def test_exact_canonical_name_wins():
    assert main._resolve_requested_model_name("llama-3", ["llama", "llama-3"]) == "llama-3"


def test_planner_alias_forms_resolve():
    assert main._resolve_requested_model_name("llama", ["llama"]) == "llama"
    assert main._resolve_requested_model_name("planner-llama", ["llama"]) == "llama"


def test_sanitized_special_characters_resolve():
    assert main._resolve_requested_model_name("org_model_tag", ["org/model:tag"]) == "org/model:tag"
    assert main._resolve_requested_model_name("planner-org_model_tag", ["org/model:tag"]) == "org/model:tag"


def test_replica_suffix_resolves_to_model():
    # A copied replica lane name (second and further lanes) is still an
    # address for the model.
    assert main._resolve_requested_model_name("planner-llama-2", ["llama"]) == "llama"
    assert main._resolve_requested_model_name("planner-llama-7", ["llama"]) == "llama"


def test_replica_suffix_does_not_shadow_numbered_sibling():
    # Regression: with llama and llama-3 deployed, planner-llama-3 is the
    # planner alias of llama-3, not a replica of llama. Before the fix both
    # tiers matched, the set had two entries, and the request 404'd.
    assert main._resolve_requested_model_name("planner-llama-3", ["llama", "llama-3"]) == "llama-3"
    assert main._resolve_requested_model_name("planner-llama-3", ["llama-3", "llama"]) == "llama-3"


def test_numbered_family_gemma():
    assert main._resolve_requested_model_name("planner-gemma-2", ["gemma", "gemma-2"]) == "gemma-2"


def test_genuine_replica_of_family_model_still_resolves():
    # The third replica of llama (index 4) is not any model's own alias.
    assert main._resolve_requested_model_name("planner-llama-4", ["llama", "llama-3"]) == "llama"


def test_replica_suffix_must_be_digit_at_least_two():
    assert main._resolve_requested_model_name("planner-llama-1", ["llama"]) is None
    assert main._resolve_requested_model_name("planner-llama-x", ["llama"]) is None


def test_shared_planner_alias_is_ambiguous():
    # Two distinct models whose names only differ in / vs : share one
    # planner-safe alias — a genuine ambiguity, refused.
    assert main._resolve_requested_model_name("planner-llama_2", ["llama/2", "llama:2"]) is None


def test_unknown_and_empty_requests_resolve_to_none():
    assert main._resolve_requested_model_name("nope", ["llama"]) is None
    assert main._resolve_requested_model_name("", ["llama"]) is None
    assert main._resolve_requested_model_name(None, ["llama"]) is None
