"""P(True) self-evaluation confidence for the autonomous tutor.

Implements the self-evaluation approach of Kadavath et al., "Language Models
(Mostly) Know What They Know" (arXiv:2207.05221): after the answer is
generated, the model is asked in a follow-up call whether its own answer is
correct, constrained to a one-word Yes/No reply, and the confidence is read
from the token log-probabilities of that reply rather than from its text:

    confidence = p_yes / (p_yes + p_no)

where p_yes and p_no sum the probability mass of all Yes/No token variants
(" Yes", "Yes", "YES", ...) at the decision position — distinct BPE tokens
that each carry real probability mass. The follow-up call must request
top_logprobs so the mass of the alternative the model did *not* sample is
visible; greedy decoding alone would hide it.

The follow-up runs after generation because self-evaluation has to condition
on the full answer, and as a separate call so the student-facing response
stays uncontaminated by confidence instructions. It continues the original
conversation (system prompt, assistant answer, self-eval question) at
temperature 0.
"""

import math
from dataclasses import dataclass
from typing import Optional

from iris.common.token_logprob_dto import TokenLogprobEntry
from iris.pipeline.shared.uncertainty_lexicon import normalize_token

# Follow-up user message appended after the assistant's answer. Both the
# pipeline helper and the offline comparison experiment import this constant
# so the two call sites can never drift apart.
SELF_EVAL_PROMPT = (
    "Look at your previous answer to the student's question. "
    "Is that answer factually correct and appropriate? "
    "Reply with exactly one word: Yes or No."
)
# Small but not 1: leaves room for a stray leading token before the decision
# token. A longer preamble truncates the decision token away and the score
# degrades to None rather than to a wrong value.
SELF_EVAL_MAX_TOKENS = 5
SELF_EVAL_TEMPERATURE = 0.0

# The prompt forces an English one-word reply, so English-only variant sets
# suffice; normalize_token folds case, whitespace, BPE markers and
# surrounding punctuation before comparison.
_YES_TOKENS = frozenset({"yes"})
_NO_TOKENS = frozenset({"no"})


@dataclass
class SelfEvalResult:
    """Score plus the raw quantities it was derived from, for auditing."""

    confidence: float
    p_yes: float
    p_no: float
    decision_token: str


def _pool(normalized: str) -> Optional[str]:
    if normalized in _YES_TOKENS:
        return "yes"
    if normalized in _NO_TOKENS:
        return "no"
    return None


def _select_decision_entry(
    entries: list[TokenLogprobEntry],
) -> Optional[TokenLogprobEntry]:
    """Pick the token position carrying the Yes/No decision.

    Prefer the first entry whose chosen token is a Yes/No variant; fall back
    to the first content-bearing entry, which covers a model that sampled an
    off-script opener while the Yes/No mass still sits in its top-k
    candidates.
    """
    fallback = None
    for entry in entries:
        normalized = normalize_token(entry.token)
        if not normalized:
            continue
        if _pool(normalized) is not None:
            return entry
        if fallback is None:
            fallback = entry
    return fallback


def self_eval_details(
    entries: Optional[list[TokenLogprobEntry]],
) -> Optional[SelfEvalResult]:
    """Score a self-evaluation reply from its token logprob entries.

    Returns None whenever the reply carries no usable Yes/No signal — no
    entries, no content-bearing token, or no Yes/No mass at the decision
    position — so the caller can fall back to another strategy. Malformed
    input degrades to None, never an exception, matching the contract of the
    other confidence strategies.
    """
    if not entries:
        return None

    entry = _select_decision_entry(entries)
    if entry is None:
        return None

    chosen = normalize_token(entry.token)
    chosen_pool = _pool(chosen)

    if not entry.top_logprobs:
        # Plain-logprob backends: without alternatives the binary pair cannot
        # be normalized; P(chosen) / 1 - P(chosen) is the standard
        # degradation.
        if chosen_pool is None:
            return None
        p_chosen = min(1.0, math.exp(entry.logprob))
        p_yes = p_chosen if chosen_pool == "yes" else 1.0 - p_chosen
        return SelfEvalResult(
            confidence=p_yes,
            p_yes=p_yes,
            p_no=1.0 - p_yes,
            decision_token=entry.token,
        )

    p_yes = 0.0
    p_no = 0.0
    if chosen_pool == "yes":
        p_yes = math.exp(entry.logprob)
    elif chosen_pool == "no":
        p_no = math.exp(entry.logprob)

    for candidate in entry.top_logprobs:
        if candidate.token == entry.token:
            # The top-k list echoes the chosen token; its probability is
            # already seeded above.
            continue
        candidate_pool = _pool(normalize_token(candidate.token))
        if candidate_pool == "yes":
            p_yes += math.exp(candidate.logprob)
        elif candidate_pool == "no":
            p_no += math.exp(candidate.logprob)

    total = p_yes + p_no
    if total <= 0.0:
        return None

    confidence = max(0.0, min(1.0, p_yes / total))
    return SelfEvalResult(
        confidence=confidence,
        p_yes=p_yes,
        p_no=p_no,
        decision_token=entry.token,
    )


def self_eval_confidence(
    entries: Optional[list[TokenLogprobEntry]],
) -> Optional[float]:
    """Confidence in [0, 1] from a self-evaluation reply, or None."""
    details = self_eval_details(entries)
    return details.confidence if details is not None else None
