"""Token-level logprob uncertainty scoring for the autonomous tutor.

Implements the uncertainty metric of Xu et al., "Logprobs Know Uncertainty:
Fighting LLM Hallucinations" (FSE '25). For each generated token the top-k
alternative candidates are classified as synonyms, antonyms, or speculative
terms; tokens with antonym or speculative candidates are uncertainty-critical,
and the response uncertainty is

    U = sum_{i=1..N} beta^(N-i) * sigma*((p_a(t_i) + gamma*p_sp(t_i)) / p_sy(t_i))

over the N uncertain tokens in response order, where p_sy/p_a/p_sp aggregate
the candidate probabilities per pool, gamma scales the speculative mass, and
beta < 1 weights uncertain tokens near the end of the response more.

Two deliberate adaptations of the paper:

* sigma* is a rescaled sigmoid, 2*(sigma(x) - 0.5) in [0, 1). The plain
  sigmoid the paper writes is >= 0.5 for any non-negative ratio, so a single
  uncertain token with negligible antonym mass would already contribute 0.5 —
  contradicting the paper's own empirical distribution, which shows a
  continuum of values near 0. The rescaled form is 0 when the contradicting
  mass is negligible and keeps the same monotonicity and saturation.
* The final uncertainty is mapped to a routing confidence in [0, 1] via
  exp(-decay * U). With the default decay 1.0, confidence crosses the Artemis
  auto-post threshold (0.95) at U ~ 0.051 and the review threshold (0.80) at
  U ~ 0.223, matching the paper's separation between reliable and
  hallucinated responses. Zero uncertain tokens give confidence 1.0.
"""

import math
from dataclasses import dataclass
from typing import Optional

from iris.common.token_logprob_dto import TokenLogprobEntry
from iris.pipeline.shared.uncertainty_lexicon import (
    are_antonyms,
    is_speculative,
    normalize_token,
)

# Paper defaults (Xu et al., section 3).
DEFAULT_GAMMA = 0.3
DEFAULT_BETA = 0.9
# Top-k candidates requested from the API (OpenAI caps top_logprobs at 20).
DEFAULT_TOP_LOGPROBS = 10
# k in confidence = exp(-k * uncertainty); calibration knob for the thesis.
DEFAULT_CONFIDENCE_DECAY = 1.0
# Denominator floor so a pathologically small synonym mass cannot blow up.
_P_SY_FLOOR = 1e-9


@dataclass
class TokenPools:
    """Aggregated candidate probability mass per pool for one token."""

    p_sy: float
    p_a: float
    p_sp: float

    @property
    def is_uncertain(self) -> bool:
        return self.p_a > 0.0 or self.p_sp > 0.0


def classify_token(entry: TokenLogprobEntry) -> Optional[TokenPools]:
    """Classify one token's top-k candidates into synonym/antonym/speculative
    pools.

    Returns None for tokens without word content (pure punctuation or
    whitespace), which carry no semantic uncertainty signal. The chosen
    token's own probability seeds the synonym pool — or the speculative pool
    when the chosen token is itself a hedge — so the denominator of the
    uncertainty ratio is never empty.
    """
    chosen = normalize_token(entry.token)
    if not chosen:
        return None

    chosen_probability = math.exp(entry.logprob)
    pools = TokenPools(p_sy=0.0, p_a=0.0, p_sp=0.0)
    if is_speculative(chosen):
        # The generated token itself hedges the statement.
        pools.p_sp = chosen_probability
    else:
        pools.p_sy = chosen_probability

    for candidate in entry.top_logprobs:
        if candidate.token == entry.token:
            # The top-k list echoes the chosen token; its probability is
            # already seeded above.
            continue
        normalized = normalize_token(candidate.token)
        if not normalized or normalized == chosen:
            # Case/whitespace/punctuation variants of the chosen token count
            # as synonyms (duplicates are summed, as in the paper).
            if normalized == chosen:
                pools.p_sy += math.exp(candidate.logprob)
            continue
        if are_antonyms(chosen, normalized):
            pools.p_a += math.exp(candidate.logprob)
        elif is_speculative(normalized):
            pools.p_sp += math.exp(candidate.logprob)

    return pools


def token_uncertainty(pools: TokenPools, *, gamma: float = DEFAULT_GAMMA) -> float:
    """Per-token uncertainty: rescaled sigmoid of the contradiction ratio."""
    ratio = (pools.p_a + gamma * pools.p_sp) / max(pools.p_sy, _P_SY_FLOOR)
    sigmoid = 1.0 / (1.0 + math.exp(-ratio))
    return 2.0 * (sigmoid - 0.5)


def sequence_uncertainty(
    entries: list[TokenLogprobEntry],
    *,
    gamma: float = DEFAULT_GAMMA,
    beta: float = DEFAULT_BETA,
) -> float:
    """Aggregate uncertainty over the response's uncertain tokens.

    Only uncertain tokens (non-empty antonym or speculative pool) enter the
    sum; beta^(N-i) gives the last uncertain token full weight and decays
    towards the beginning of the response, per the paper's recency argument.
    """
    uncertain = []
    for entry in entries:
        pools = classify_token(entry)
        if pools is not None and pools.is_uncertain:
            uncertain.append(token_uncertainty(pools, gamma=gamma))

    total = len(uncertain)
    return sum(
        beta ** (total - i) * value for i, value in enumerate(uncertain, start=1)
    )


def uncertainty_confidence(
    entries: Optional[list[TokenLogprobEntry]],
    *,
    gamma: float = DEFAULT_GAMMA,
    beta: float = DEFAULT_BETA,
    decay: float = DEFAULT_CONFIDENCE_DECAY,
) -> Optional[float]:
    """Derive a confidence score in [0, 1] from rich token logprob entries.

    Returns None when the paper method cannot be applied — no entries, or no
    entry carries top-k alternatives (backends that return plain logprobs
    without top_logprobs) — so the caller falls back to the mean-logprob
    strategy. A response with zero uncertain tokens scores 1.0, faithful to
    the paper: confidence is about contradiction mass in the prediction sets,
    not about raw token probability.
    """
    if not entries or not any(entry.top_logprobs for entry in entries):
        return None

    uncertainty = sequence_uncertainty(entries, gamma=gamma, beta=beta)
    return max(0.0, min(1.0, math.exp(-decay * uncertainty)))
