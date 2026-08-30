"""Tests for the router's privacy gate (pipeline._privacy_ok / PRIVACY_ORDER).

The gate decides which deployments may serve a request given the policy's
threshold_privacy. It is a security decision: the failure mode is not a
misrouting but an over-routing — a deployment receiving more confidential
data than the caller asked to keep away from it.
"""

from logos.dbutils.dbmanager import VALID_PRIVACY_LEVELS
from logos.dbutils.dbmodules import ThresholdLevel
from logos.pipeline.pipeline import PRIVACY_ORDER, _privacy_ok


def test_order_is_trust_descending_and_complete() -> None:
    # The declaration order of ThresholdLevel IS the ordering; a copy that
    # drifts from it (or loses a level) fails here.
    assert PRIVACY_ORDER == tuple(level.value for level in ThresholdLevel)
    assert set(PRIVACY_ORDER) == VALID_PRIVACY_LEVELS
    # Most trusted first, third-party hardware last: a Mac lane must never
    # outrank a datacentre box.
    assert PRIVACY_ORDER[0] == "LOCAL"
    assert PRIVACY_ORDER[-1] == "THIRD_PARTY_HARDWARE"


def test_local_threshold_is_datacentre_only() -> None:
    # The acute gap: a caller demanding LOCAL must not be routed to a
    # personal Mac, even though LOCAL used to be the *default* provider
    # level.
    assert _privacy_ok("LOCAL", "LOCAL")
    assert not _privacy_ok("LOCAL", "CLOUD_IN_EU_BY_EU_PROVIDER")
    assert not _privacy_ok("LOCAL", "CLOUD_IN_EU_BY_US_PROVIDER")
    assert not _privacy_ok("LOCAL", "CLOUD_NOT_IN_EU_BY_US_PROVIDER")
    assert not _privacy_ok("LOCAL", "THIRD_PARTY_HARDWARE")


def test_third_party_hardware_is_opt_in_only() -> None:
    # A Mac lane serves only requests whose policy explicitly allows
    # third-party hardware — which, being the least trusted tier, allows
    # every deployment.
    assert _privacy_ok("THIRD_PARTY_HARDWARE", "LOCAL")
    assert _privacy_ok("THIRD_PARTY_HARDWARE", "CLOUD_NOT_IN_EU_BY_US_PROVIDER")
    assert _privacy_ok("THIRD_PARTY_HARDWARE", "THIRD_PARTY_HARDWARE")


def test_intermediate_thresholds_keep_their_ordering() -> None:
    assert _privacy_ok("CLOUD_IN_EU_BY_EU_PROVIDER", "LOCAL")
    assert _privacy_ok("CLOUD_IN_EU_BY_EU_PROVIDER", "CLOUD_IN_EU_BY_EU_PROVIDER")
    assert not _privacy_ok("CLOUD_IN_EU_BY_EU_PROVIDER", "CLOUD_NOT_IN_EU_BY_US_PROVIDER")
    assert not _privacy_ok("CLOUD_IN_EU_BY_EU_PROVIDER", "THIRD_PARTY_HARDWARE")


def test_unknown_threshold_fails_closed_to_strictest() -> None:
    # A typo in a policy must not accept every deployment — it may accept
    # only the most trusted ones.
    assert _privacy_ok("TYPO_LEVEL", "LOCAL")
    assert not _privacy_ok("TYPO_LEVEL", "CLOUD_IN_EU_BY_EU_PROVIDER")
    assert not _privacy_ok("TYPO_LEVEL", "THIRD_PARTY_HARDWARE")


def test_unknown_level_fails_closed_to_least_trusted() -> None:
    # A deployment type the router has not been taught about (e.g. a new
    # enum value that reached the DB before the router did) must not
    # qualify for the strictest requests.
    assert not _privacy_ok("LOCAL", "FUTURE_LEVEL")
    assert not _privacy_ok("CLOUD_IN_EU_BY_US_PROVIDER", "FUTURE_LEVEL")
    assert _privacy_ok("THIRD_PARTY_HARDWARE", "FUTURE_LEVEL")
