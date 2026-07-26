from typing import List

from pydantic import BaseModel, Field


class TopLogprobCandidate(BaseModel):
    """An alternative token the model considered at one generation step."""

    token: str
    logprob: float


class TokenLogprobEntry(BaseModel):
    """Log-probability data for one generated token.

    ``top_logprobs`` holds the top-k alternative candidates at this position
    (empty when the backend returns plain logprobs without alternatives, in
    which case only the mean-logprob confidence strategy can be applied).
    """

    token: str
    logprob: float
    top_logprobs: List[TopLogprobCandidate] = Field(default_factory=list)
