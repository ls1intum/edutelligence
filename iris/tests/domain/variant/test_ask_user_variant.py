from unittest.mock import patch

from iris.domain.variant.ask_user_variant import AskUserVariant


def test_defaults_guide_and_local_models_to_agent_model_when_omitted():
    variant = AskUserVariant(
        variant_id="default",
        name="Default",
        description="desc",
        agent_model="cloud-agent",
    )

    assert variant.agent_model == "cloud-agent"
    assert variant.guide_model == "cloud-agent"
    assert variant.model("chat", local=False) == "cloud-agent"
    assert variant.model("chat", local=True) == "cloud-agent"
    assert variant.model("guide", local=False) == "cloud-agent"
    assert variant.model("guide", local=True) == "cloud-agent"


def test_required_models_deduplicates_identical_ids():
    variant = AskUserVariant(
        variant_id="default",
        name="Default",
        description="desc",
        agent_model="cloud-agent",
    )

    # agent/guide/local all fall back to the same id -> single required model
    assert variant.required_models() == {"cloud-agent"}


def test_explicit_guide_and_local_models_are_kept_distinct():
    variant = AskUserVariant(
        variant_id="advanced",
        name="Advanced",
        description="desc",
        agent_model="cloud-agent",
        guide_model="cloud-guide",
        local_agent_model="local-agent",
        local_guide_model="local-guide",
    )

    assert variant.model("chat", local=False) == "cloud-agent"
    assert variant.model("chat", local=True) == "local-agent"
    assert variant.model("guide", local=False) == "cloud-guide"
    assert variant.model("guide", local=True) == "local-guide"
    assert variant.required_models() == {
        "cloud-agent",
        "cloud-guide",
        "local-agent",
        "local-guide",
    }


def test_local_guide_model_falls_back_to_guide_model_when_only_guide_model_given():
    variant = AskUserVariant(
        variant_id="advanced",
        name="Advanced",
        description="desc",
        agent_model="cloud-agent",
        guide_model="cloud-guide",
    )

    # local_guide_model was not given explicitly, so it should mirror guide_model,
    # not fall all the way back to agent_model.
    assert variant.model("guide", local=True) == "cloud-guide"


def test_distinct_local_model_is_ignored_when_local_llm_globally_disabled():
    # Mirrors resolve_model()'s kill switch: a deployment that has turned off
    # local LLM support entirely must never route to a self-hosted model,
    # even if the variant declares one.
    with patch(
        "iris.domain.variant.ask_user_variant.settings",
        local_llm_enabled=False,
    ):
        variant = AskUserVariant(
            variant_id="default",
            name="Default",
            description="desc",
            agent_model="cloud-agent",
            guide_model="cloud-guide",
            local_agent_model="local-agent",
            local_guide_model="local-guide",
        )

    assert variant.model("chat", local=True) == "cloud-agent"
    assert variant.model("guide", local=True) == "cloud-guide"
    assert variant.required_models() == {"cloud-agent", "cloud-guide"}


def test_feature_dto_exposes_identity_fields():
    variant = AskUserVariant(
        variant_id="default",
        name="Default",
        description="Uses a smaller model.",
        agent_model="cloud-agent",
    )

    feature = variant.feature_dto()

    assert feature.id == "default"
    assert feature.name == "Default"
    assert feature.description == "Uses a smaller model."
