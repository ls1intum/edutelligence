"""Regression tests for the logos model-string parser.

The policy section is a run of "key=value" pairs delimited by known keys,
and the pairs themselves sit inside an underscore-separated string. Values
may contain underscores — the privacy tiers do (THIRD_PARTY_HARDWARE) — so a
plain split on "_" shreds them into misplaced fragments and the string is
rejected with a SyntaxError. Only LOCAL, the underscore-free tier, ever
parsed before the fix.
"""

import pytest

from logos.model_string_parser import parse_model_string


class TestPolicyParsing:
    def test_default_policy(self):
        dto = parse_model_string("logos-v1.0__policy_default=true")
        assert dto.version == "1.0"
        assert dto.policy == {"default": True}

    def test_single_policy_attribute(self):
        dto = parse_model_string("logos-v1.0__policy_default=false__policy_latency=LOW")
        assert dto.policy == {"default": False, "latency": "LOW"}

    def test_multiple_policy_attributes(self):
        dto = parse_model_string("logos-v1.0__policy_default=false__policy_latency=LOW__policy_cost=LOW")
        assert dto.policy == {"default": False, "latency": "LOW", "cost": "LOW"}

    @pytest.mark.parametrize(
        "tier",
        [
            "LOCAL",
            "CLOUD_IN_EU_BY_EU_PROVIDER",
            "CLOUD_IN_EU_BY_US_PROVIDER",
            "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
            "THIRD_PARTY_HARDWARE",
        ],
    )
    def test_privacy_tiers_with_underscores_stay_intact(self, tier):
        """Every tier the DB enum allows must parse — before the fix, all
        but LOCAL raised SyntaxError."""
        dto = parse_model_string(f"logos-v1.0__policy_default=false__policy_privacy={tier}")
        assert dto.policy["privacy"] == tier

    def test_privacy_tier_kept_when_adjacent_attributes_follow(self):
        dto = parse_model_string(
            "logos-v1.0__policy_default=false__policy_privacy=THIRD_PARTY_HARDWARE__policy_cost=LOW"
        )
        assert dto.policy["privacy"] == "THIRD_PARTY_HARDWARE"
        assert dto.policy["cost"] == "LOW"

    def test_invalid_privacy_value_rejected(self):
        with pytest.raises(SyntaxError):
            parse_model_string("logos-v1.0__policy_default=false__policy_privacy=NOWHERE")

    def test_unknown_policy_key_rejected(self):
        with pytest.raises(SyntaxError):
            parse_model_string("logos-v1.0__policy_default=false__policy_bogus=1")

    def test_non_default_policy_without_attributes_rejected(self):
        with pytest.raises(AttributeError):
            parse_model_string("logos-v1.0__policy_default=false")

    def test_bad_default_value_rejected(self):
        with pytest.raises(AttributeError):
            parse_model_string("logos-v1.0__policy_default=yes")

    def test_string_must_start_with_logos_v(self):
        with pytest.raises(SyntaxError):
            parse_model_string("other-v1.0__policy_default=true")

    def test_unknown_extra_fields_are_filtered_out(self):
        dto = parse_model_string("logos-v1.0__policy_default=true__foo=bar")
        assert dto.extra == {}
