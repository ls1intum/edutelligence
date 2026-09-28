"""Provider-independent Hugging Face reachability check for a model repository.

Answers only whether the central HF_TOKEN can see the repository, never whether
a node could serve the model. Reason codes match the worker's HF precheck.
"""

import asyncio
import datetime
import logging
import math
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

STATUS_REACHABLE = "reachable"
STATUS_REJECTED = "rejected"
STATUS_UNKNOWN = "unknown"

REASON_INVALID_REPO_ID = "invalid-repo-id"
REASON_MODEL_NOT_FOUND_OR_UNAUTHORIZED = "model-not-found-or-unauthorized"
REASON_MODEL_GATED = "model-gated"

_DEFAULT_TIMEOUT_S = 15.0


def _timeout_from_env() -> float:
    # Read at import time by the router, so a bad value must not raise.
    raw = os.getenv("LOGOS_HF_REACHABILITY_TIMEOUT_S", "")
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not math.isfinite(value) or value <= 0:
        if raw:
            logger.warning("Ignoring invalid LOGOS_HF_REACHABILITY_TIMEOUT_S=%r", raw)
        return _DEFAULT_TIMEOUT_S
    return value


_TIMEOUT_S = _timeout_from_env()


@dataclass(frozen=True)
class HfReachability:
    hf_repo_id: str
    status: str
    reason_code: str | None
    detail: str | None
    checked_at: str


def _check_sync(hf_repo_id: str, token: str | None) -> tuple[str, str | None, str | None]:
    from huggingface_hub import HfApi
    from huggingface_hub.errors import GatedRepoError, HFValidationError, RepositoryNotFoundError
    from huggingface_hub.utils import validate_repo_id

    try:
        # auth_check doesn't validate the id; a malformed one would 404.
        validate_repo_id(hf_repo_id)
        # False, not None: None would fall back to a token cached on disk.
        HfApi().auth_check(hf_repo_id, token=token or False)
    except HFValidationError:
        return STATUS_REJECTED, REASON_INVALID_REPO_ID, "Not a valid Hugging Face repository id."
    # GatedRepoError subclasses RepositoryNotFoundError, so it must come first.
    except GatedRepoError:
        return STATUS_REJECTED, REASON_MODEL_GATED, "Repository access requires an authorized HF_TOKEN."
    except RepositoryNotFoundError:
        # The Hub answers identically for a missing repo and a private one.
        return (
            STATUS_REJECTED,
            REASON_MODEL_NOT_FOUND_OR_UNAUTHORIZED,
            "Repository does not exist or is not visible to the configured HF_TOKEN.",
        )
    except Exception:  # noqa: BLE001
        # Library/network errors can name internal hosts or proxies; log only.
        logger.warning("HF reachability check failed for %s", hf_repo_id, exc_info=True)
        return STATUS_UNKNOWN, None, "Hugging Face Hub could not be reached."
    return STATUS_REACHABLE, None, None


async def check_hf_reachability(hf_repo_id: str) -> HfReachability:
    """Check one repository against the Hub. Never raises.

    ``unknown`` (network error, Hub outage, timeout) is not a verdict about the
    repository, so callers must not store it as one.
    """
    repo_id = hf_repo_id.strip()
    token = os.getenv("HF_TOKEN", "").strip() or None
    try:
        status, reason_code, detail = await asyncio.wait_for(
            asyncio.to_thread(_check_sync, repo_id, token), timeout=_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        status, reason_code, detail = STATUS_UNKNOWN, None, f"Hugging Face Hub did not answer within {_TIMEOUT_S:g}s."
    return HfReachability(
        hf_repo_id=repo_id,
        status=status,
        reason_code=reason_code,
        detail=detail,
        checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
