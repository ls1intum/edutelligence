"""Tests for the rule that agent work never bills a cloud provider.

The policy is evaluated against rows shaped like the deployment query's
result, because that is the shape the runner actually reads: a model, a
provider type, and the aliases that resolve to the same model.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from app import model_policy


def deployment(model: str, provider_type: str, aliases: str | None = None) -> dict:
    return {
        "model_id": abs(hash(model)) % 10_000,
        "model_name": model,
        "provider_id": 1,
        "provider_type": provider_type,
        "aliases": aliases,
    }


class TestClassification:
    def test_a_locally_served_model_is_allowed(self):
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode")])
        assert policy.ok
        assert policy.allows("Qwen3-8B")
        assert policy.offered == ("Qwen3-8B",)

    def test_model_names_are_matched_case_insensitively(self):
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode")])
        assert policy.allows("qwen3-8b")

    def test_aliases_of_a_local_model_are_allowed_but_not_offered(self):
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode", aliases="local-fast,house-model")])
        assert policy.allows("local-fast")
        assert policy.allows("house-model")
        # The picker offers models, not every name that resolves to one.
        assert policy.offered == ("Qwen3-8B",)

    def test_a_cloud_deployment_stops_every_session(self):
        policy = model_policy.evaluate(
            [
                deployment("Qwen3-8B", "logosnode"),
                deployment("gpt-4o", "cloud"),
            ]
        )
        assert not policy.ok
        # Not merely the cloud model: nothing runs while the key can spend
        # money at all, because the next request could name it.
        assert not policy.allows("Qwen3-8B")
        assert "gpt-4o" in policy.detail

    def test_azure_counts_as_cloud(self):
        policy = model_policy.evaluate([deployment("gpt-4o", "azure")])
        assert not policy.ok
        assert "gpt-4o" in policy.cloud_models

    def test_an_unknown_provider_type_is_not_assumed_free(self):
        policy = model_policy.evaluate([deployment("mystery", "some-new-backend")])
        assert not policy.ok
        assert "mystery" in policy.cloud_models

    def test_a_model_served_both_locally_and_in_the_cloud_counts_as_cloud(self):
        local, cloud, offered = model_policy.classify(
            [
                deployment("shared", "logosnode"),
                deployment("shared", "cloud"),
            ]
        )
        # The scheduler may route to either provider, so the cheap one being
        # available is no guarantee the expensive one is not used.
        assert "shared" not in local
        assert "shared" in cloud
        assert offered == ()

    def test_an_alias_of_a_cloud_model_is_refused(self):
        policy = model_policy.evaluate([deployment("gpt-4o", "cloud", aliases="smartest")])
        assert "smartest" in policy.cloud_models
        assert not policy.allows("smartest")

    def test_nothing_reachable_is_not_permission_to_run(self):
        policy = model_policy.evaluate([])
        assert not policy.ok
        assert not policy.unknown  # a clean answer, just not a usable one

    def test_an_unevaluated_policy_refuses(self):
        assert not model_policy.UNKNOWN.ok
        assert model_policy.UNKNOWN.unknown
        assert not model_policy.UNKNOWN.allows("anything")


class TestDefaultModel:
    def test_a_single_local_model_needs_no_configuration(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, default_model=""))
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode")])
        assert policy.default_model == "Qwen3-8B"
        assert policy.allows(None)
        assert policy.resolve(None) == "Qwen3-8B"

    def test_several_local_models_require_the_session_to_name_one(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, default_model=""))
        policy = model_policy.evaluate(
            [
                deployment("Qwen3-8B", "logosnode"),
                deployment("Llama-3-70B", "logosnode"),
            ]
        )
        assert policy.default_model == ""
        assert not policy.allows(None)
        assert "Name one" in policy.refusal(None)
        assert policy.allows("Llama-3-70B")

    def test_a_configured_default_wins(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, default_model="Llama-3-70B"))
        policy = model_policy.evaluate(
            [
                deployment("Qwen3-8B", "logosnode"),
                deployment("Llama-3-70B", "logosnode"),
            ]
        )
        assert policy.default_model == "Llama-3-70B"
        assert policy.allows(None)

    def test_a_configured_default_that_is_not_local_is_refused(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, default_model="gpt-4o"))
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode")])
        assert policy.default_model == ""
        assert not policy.allows(None)
        assert "gpt-4o" in policy.refusal(None)


class TestRefusalWording:
    def test_a_cloud_model_is_refused_as_a_cloud_model(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, default_model=""))
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode")])
        # 'gpt-4o' is not reachable at all here, so the refusal is the
        # not-served-locally one; the cloud wording is reserved for a name
        # the key really can bill.
        assert "not among the locally served models" in policy.refusal("gpt-4o")

    def test_the_refusal_lists_what_is_available(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, default_model=""))
        policy = model_policy.evaluate([deployment("Qwen3-8B", "logosnode")])
        assert "Qwen3-8B" in policy.refusal("something-else")


class TestLoad:
    @pytest.mark.asyncio
    async def test_an_unconfigured_key_yields_an_unknown_policy(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, agent_api_key=""))
        policy = await model_policy.load()
        assert not policy.ok
        assert policy.unknown

    @pytest.mark.asyncio
    async def test_a_key_the_platform_does_not_know_yields_unknown(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, agent_api_key="lg-nope"))

        async def no_such_key(_key: str) -> bool:
            return False

        monkeypatch.setattr(model_policy.db, "agent_key_exists", no_such_key)
        policy = await model_policy.load()
        assert not policy.ok
        assert policy.unknown
        assert "not an active key" in policy.detail

    @pytest.mark.asyncio
    async def test_an_unreadable_database_is_not_permission(self, monkeypatch):
        monkeypatch.setattr(model_policy, "settings", replace(model_policy.settings, agent_api_key="lg-key"))

        async def key_exists(_key: str) -> bool:
            return True

        async def boom(_key: str):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(model_policy.db, "agent_key_exists", key_exists)
        monkeypatch.setattr(model_policy.db, "reachable_deployments", boom)
        policy = await model_policy.load()
        assert not policy.ok
        assert policy.unknown


class TestTheLane:
    """Which deployments a capacity reading may count.

    A model name is not enough: the same model is served by providers this
    key has no permission for, and counting their idle slots would make a
    busy lane look free.
    """

    def test_the_reachable_local_deployments_are_kept(self):
        policy = model_policy.evaluate(
            [
                {"provider_id": 15, "model_id": 97, "model_name": "Qwen/Qwen3.8-27B", "provider_type": "logosnode"},
                {"provider_id": 61, "model_id": 97, "model_name": "Qwen/Qwen3.8-27B", "provider_type": "logosnode"},
            ]
        )

        assert policy.lane() == frozenset({("15", "97"), ("61", "97")})

    def test_a_cloud_tainted_model_brings_no_lane(self):
        policy = model_policy.evaluate(
            [
                {"provider_id": 15, "model_id": 97, "model_name": "gpt-4o", "provider_type": "logosnode"},
                {"provider_id": 3, "model_id": 97, "model_name": "gpt-4o", "provider_type": "azure"},
            ]
        )

        # The policy refuses anyway; the lane must not quietly say otherwise.
        assert policy.ok is False
        assert policy.lane() == frozenset()

    def test_an_unevaluated_policy_has_no_lane(self):
        assert model_policy.UNKNOWN.lane() == frozenset()
