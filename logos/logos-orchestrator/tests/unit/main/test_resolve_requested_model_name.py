"""Tests for _resolve_requested_model_name.

Covers the planner-alias and replica-suffix resolution tiers, including the
numeric-suffix family collision (llama + llama-3) that made
planner-llama-3 unresolvable while both were deployed.
"""

import logos as main


def _row(name: str, aliases: list[str] | None = None) -> dict:
    return {"name": name, "aliases": aliases or []}


def test_exact_canonical_name_wins():
    assert main._resolve_requested_model_name("llama-3", [_row("llama"), _row("llama-3")]) == "llama-3"


def test_planner_alias_forms_resolve():
    assert main._resolve_requested_model_name("llama", [_row("llama")]) == "llama"
    assert main._resolve_requested_model_name("planner-llama", [_row("llama")]) == "llama"


def test_matching_is_case_insensitive():
    assert main._resolve_requested_model_name("LLAMA", [_row("llama")]) == "llama"
    assert main._resolve_requested_model_name("Planner-LLAMA", [_row("llama")]) == "llama"
    assert main._resolve_requested_model_name("planner-LLAMA-2", [_row("llama")]) == "llama"


def test_sanitized_special_characters_resolve():
    assert main._resolve_requested_model_name("org_model_tag", [_row("org/model:tag")]) == "org/model:tag"
    assert main._resolve_requested_model_name("planner-org_model_tag", [_row("org/model:tag")]) == "org/model:tag"


def test_replica_suffix_resolves_to_model():
    # A copied replica lane name (second and further lanes) is still an
    # address for the model.
    assert main._resolve_requested_model_name("planner-llama-2", [_row("llama")]) == "llama"
    assert main._resolve_requested_model_name("planner-llama-7", [_row("llama")]) == "llama"


def test_replica_suffix_does_not_shadow_numbered_sibling():
    # Regression: with llama and llama-3 deployed, planner-llama-3 is the
    # planner alias of llama-3, not a replica of llama. Before the fix both
    # tiers matched, the set had two entries, and the request 404'd.
    assert main._resolve_requested_model_name("planner-llama-3", [_row("llama"), _row("llama-3")]) == "llama-3"
    assert main._resolve_requested_model_name("planner-llama-3", [_row("llama-3"), _row("llama")]) == "llama-3"


def test_numbered_family_gemma():
    assert main._resolve_requested_model_name("planner-gemma-2", [_row("gemma"), _row("gemma-2")]) == "gemma-2"


def test_replica_suffix_does_not_shadow_stored_alias():
    # The stored alias of another model is an explicit assignment the replica
    # tier must not shadow: llama's second lane id collides with it, no tier
    # then matches, and the request is refused instead of guessing.
    rows = [_row("llama"), _row("big-model", aliases=["llama-2"])]
    assert main._resolve_requested_model_name("planner-llama-2", rows) is None


def test_genuine_replica_of_family_model_still_resolves():
    # The third replica of llama (index 4) is not any model's own alias.
    assert main._resolve_requested_model_name("planner-llama-4", [_row("llama"), _row("llama-3")]) == "llama"


def test_replica_suffix_must_be_digit_at_least_two():
    assert main._resolve_requested_model_name("planner-llama-1", [_row("llama")]) is None
    assert main._resolve_requested_model_name("planner-llama-x", [_row("llama")]) is None


def test_replica_suffix_must_be_ascii_decimal():
    # The planner derives suffixes from int, so a replica id is ASCII decimal
    # only: a non-ASCII "digit" never names a lane, and a run longer than
    # int() can parse is refused instead of raising out of the resolver.
    assert main._resolve_requested_model_name("planner-llama-" + "٢", [_row("llama")]) is None
    assert main._resolve_requested_model_name("planner-llama-" + "9" * 5000, [_row("llama")]) is None
    assert main._resolve_requested_model_name("planner-llama-2", [_row("llama")]) == "llama"


def test_shared_planner_alias_is_ambiguous():
    # Two distinct models whose names only differ in / vs : share one
    # planner-safe alias — a genuine ambiguity, refused even though the
    # request also looks like a replica id of one of them.
    assert main._resolve_requested_model_name("planner-llama_2", [_row("llama/2"), _row("llama:2")]) is None


def test_unknown_and_empty_requests_resolve_to_none():
    assert main._resolve_requested_model_name("nope", [_row("llama")]) is None
    assert main._resolve_requested_model_name("", [_row("llama")]) is None
    assert main._resolve_requested_model_name(None, [_row("llama")]) is None
