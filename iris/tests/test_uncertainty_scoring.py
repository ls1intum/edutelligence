import math

# Establish module import order (see note in other tests).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.token_logprob_dto import (  # noqa: E402
    TokenLogprobEntry,
    TopLogprobCandidate,
)
from iris.pipeline.shared.uncertainty_lexicon import (  # noqa: E402
    are_antonyms,
    is_speculative,
    normalize_token,
)
from iris.pipeline.shared.uncertainty_scoring import (  # noqa: E402
    classify_token,
    sequence_uncertainty,
    token_uncertainty,
    uncertainty_confidence,
)


def _entry(token, prob, candidates=()):
    """Build a TokenLogprobEntry from probabilities (not logprobs)."""
    return TokenLogprobEntry(
        token=token,
        logprob=math.log(prob),
        top_logprobs=[
            TopLogprobCandidate(token=t, logprob=math.log(p)) for t, p in candidates
        ],
    )


def _rescaled_sigmoid(x):
    return 2.0 * (1.0 / (1.0 + math.exp(-x)) - 0.5)


# ──────────────────────────────────────────────────────────────────────────
# Lexicon: normalization
# ──────────────────────────────────────────────────────────────────────────
def test_normalize_strips_bpe_markers_whitespace_punctuation_and_casefolds():
    assert normalize_token("Ġno") == "no"
    assert normalize_token("▁ja") == "ja"
    assert normalize_token(" No.") == "no"
    assert normalize_token("YES") == "yes"
    assert normalize_token("##falsch") == "falsch"


def test_normalize_pure_punctuation_is_empty():
    assert normalize_token("...") == ""
    assert normalize_token(" ") == ""
    assert normalize_token("«»") == ""


# ──────────────────────────────────────────────────────────────────────────
# Lexicon: antonyms and speculative terms
# ──────────────────────────────────────────────────────────────────────────
def test_lexicon_antonym_pairs_english_and_german():
    assert are_antonyms("yes", "no")
    assert are_antonyms("no", "yes")  # symmetric
    assert are_antonyms("true", "false")
    assert are_antonyms("wahr", "falsch")
    assert are_antonyms("links", "rechts")
    assert are_antonyms("erste", "zweite")
    assert not are_antonyms("yes", "yes")
    assert not are_antonyms("apple", "banana")


def test_negation_prefix_heuristic():
    assert are_antonyms("certain", "uncertain")
    assert are_antonyms("uncertain", "certain")
    assert are_antonyms("gültig", "ungültig")
    assert are_antonyms("possible", "impossible")
    # Stems shorter than 3 characters are not misread as negations.
    assert not are_antonyms("on", "non")


def test_standalone_negator_is_directional():
    # A negator candidate contradicts a non-negator chosen token …
    assert are_antonyms("works", "not")
    assert are_antonyms("funktioniert", "nicht")
    # … but a negator chosen token is not contradicted by arbitrary words.
    assert not are_antonyms("not", "works")
    # Two negators are not antonyms of each other.
    assert not are_antonyms("not", "nicht")


def test_cs_antonym_pairs():
    assert are_antonyms("stack", "heap")
    assert are_antonyms("public", "private")
    assert are_antonyms("overload", "override")
    assert are_antonyms("depth", "breadth")
    assert are_antonyms("merge", "rebase")
    assert are_antonyms("sync", "async")
    # Explicit pairs whose prefixes are (deliberately) not negation prefixes.
    assert are_antonyms("serialize", "deserialize")
    assert are_antonyms("allocate", "deallocate")
    # A token may belong to several pairs.
    assert are_antonyms("push", "pop")
    assert are_antonyms("push", "pull")
    assert not are_antonyms("pop", "pull")


def test_ml_and_security_antonym_pairs():
    # ML / math / graphs
    assert are_antonyms("generative", "discriminative")
    assert are_antonyms("precision", "recall")
    assert are_antonyms("prior", "posterior")
    assert are_antonyms("continuous", "discrete")
    assert are_antonyms("over", "under")
    assert are_antonyms("cyclic", "acyclic")
    assert are_antonyms("nodes", "edges")
    assert are_antonyms("training", "test")
    # systems / C
    assert are_antonyms("value", "reference")
    assert are_antonyms("bit", "byte")
    assert are_antonyms("big", "little")
    # security
    assert are_antonyms("symmetric", "asymmetric")
    assert are_antonyms("authentication", "authorization")
    assert are_antonyms("plaintext", "ciphertext")
    # Prefix-derivable ML contrasts need no lexicon entry.
    assert are_antonyms("supervised", "unsupervised")
    assert are_antonyms("linear", "nonlinear")
    assert are_antonyms("convex", "nonconvex")
    assert are_antonyms("directed", "undirected")


def test_cs_pair_drives_uncertainty_scoring():
    # "allocated on the stack" while the model seriously considered "heap".
    entries = [_entry(" stack", 0.55, candidates=[(" heap", 0.4)])]
    expected_u = _rescaled_sigmoid(0.4 / 0.55)
    assert math.isclose(sequence_uncertainty(entries), expected_u)
    assert uncertainty_confidence(entries) < 0.80  # below the review tier


def test_speculative_terms_english_and_german():
    assert is_speculative("likely")
    assert is_speculative("maybe")
    assert is_speculative("vielleicht")
    assert is_speculative("vermutlich")
    assert not is_speculative("definitely")


# ──────────────────────────────────────────────────────────────────────────
# classify_token: candidate pools
# ──────────────────────────────────────────────────────────────────────────
def test_classify_token_pools_antonym_and_synonym_mass():
    entry = _entry(" Yes", 0.5, candidates=[(" yes", 0.2), ("YES", 0.1), (" No", 0.15)])
    pools = classify_token(entry)
    assert math.isclose(pools.p_sy, 0.8)  # chosen + case variants
    assert math.isclose(pools.p_a, 0.15)
    assert pools.p_sp == 0.0
    assert pools.is_uncertain


def test_classify_token_skips_exact_echo_of_chosen_token():
    # OpenAI's top-k list includes the sampled token itself; its probability
    # must not be counted twice.
    entry = _entry(" Yes", 0.6, candidates=[(" Yes", 0.6), (" No", 0.3)])
    pools = classify_token(entry)
    assert math.isclose(pools.p_sy, 0.6)
    assert math.isclose(pools.p_a, 0.3)


def test_classify_token_speculative_candidates():
    entry = _entry(" is", 0.7, candidates=[(" likely", 0.2), (" vielleicht", 0.05)])
    pools = classify_token(entry)
    assert math.isclose(pools.p_sp, 0.25)
    assert pools.is_uncertain


def test_classify_token_hedged_chosen_token_seeds_speculative_pool():
    entry = _entry(" likely", 0.6, candidates=[(" definitely", 0.2)])
    pools = classify_token(entry)
    assert pools.p_sy == 0.0
    assert math.isclose(pools.p_sp, 0.6)


def test_classify_token_punctuation_is_skipped():
    assert classify_token(_entry(".", 0.9, candidates=[(" no", 0.05)])) is None


# ──────────────────────────────────────────────────────────────────────────
# Uncertainty formula
# ──────────────────────────────────────────────────────────────────────────
def test_single_antonym_token_matches_hand_computed_value():
    entries = [_entry(" Yes", 0.6, candidates=[(" No", 0.3)])]
    expected_u = _rescaled_sigmoid(0.3 / 0.6)
    assert math.isclose(sequence_uncertainty(entries), expected_u)
    assert math.isclose(uncertainty_confidence(entries), math.exp(-expected_u))


def test_gamma_scales_speculative_mass_below_antonym_mass():
    antonym = [_entry(" Yes", 0.6, candidates=[(" No", 0.3)])]
    speculative = [_entry(" Yes", 0.6, candidates=[(" maybe", 0.3)])]
    u_antonym = sequence_uncertainty(antonym)
    u_speculative = sequence_uncertainty(speculative)
    assert math.isclose(u_speculative, _rescaled_sigmoid(0.3 * 0.3 / 0.6))
    assert u_speculative < u_antonym


def test_beta_weights_later_uncertain_tokens_more():
    weak = _entry(" true", 0.9, candidates=[(" false", 0.05)])
    strong = _entry(" Yes", 0.5, candidates=[(" No", 0.45)])
    filler = _entry(" the", 0.99)  # certain token, must not shift exponents

    u_strong_last = sequence_uncertainty([weak, filler, strong])
    u_strong_first = sequence_uncertainty([strong, filler, weak])
    u_weak = sequence_uncertainty([weak])
    u_strong = sequence_uncertainty([strong])

    beta = 0.9
    assert math.isclose(u_strong_last, beta * u_weak + u_strong)
    assert math.isclose(u_strong_first, beta * u_strong + u_weak)
    # The response whose strongly-contested token comes later is more uncertain.
    assert u_strong_last > u_strong_first


def test_rescaled_sigmoid_negligible_mass_yields_near_zero():
    entries = [_entry(" Yes", 0.9, candidates=[(" No", 1e-12)])]
    # The paper's plain sigmoid would yield >= 0.5 here.
    assert sequence_uncertainty(entries) < 1e-9


def test_p_sy_floor_prevents_division_blowup():
    # Chosen token with astronomically small probability still yields a
    # finite score in [0, 1].
    entries = [_entry(" yes", 1e-30, candidates=[(" no", 0.5)])]
    uncertainty = sequence_uncertainty(entries)
    assert math.isfinite(uncertainty)
    assert 0.0 <= uncertainty <= 1.0
    assert 0.0 <= uncertainty_confidence(entries) <= 1.0


def test_zero_uncertain_tokens_is_full_confidence():
    entries = [
        _entry(" The", 0.8, candidates=[(" A", 0.1), (" This", 0.05)]),
        _entry(" answer", 0.9, candidates=[(" result", 0.05)]),
    ]
    assert sequence_uncertainty(entries) == 0.0
    assert uncertainty_confidence(entries) == 1.0


def test_confidence_decay_kwarg_respected():
    entries = [_entry(" Yes", 0.6, candidates=[(" No", 0.3)])]
    uncertainty = sequence_uncertainty(entries)
    assert math.isclose(
        uncertainty_confidence(entries, decay=2.0), math.exp(-2.0 * uncertainty)
    )


# ──────────────────────────────────────────────────────────────────────────
# Fallback contract: None means "use the mean-logprob strategy"
# ──────────────────────────────────────────────────────────────────────────
def test_uncertainty_confidence_none_without_entries():
    assert uncertainty_confidence(None) is None
    assert uncertainty_confidence([]) is None


def test_uncertainty_confidence_none_without_top_candidates():
    # Plain-logprob backends: entries exist but carry no alternatives.
    entries = [_entry("ok", 0.9), _entry("!", 0.8)]
    assert uncertainty_confidence(entries) is None


def test_token_uncertainty_bounded_in_unit_interval():
    # Mathematically the rescaled sigmoid is < 1, but it saturates to exactly
    # 1.0 in floating point for overwhelming contradiction ratios.
    entries = [_entry(" yes", 0.01, candidates=[(" no", 0.99)])]
    pools = classify_token(entries[0])
    assert 0.0 <= token_uncertainty(pools) <= 1.0
