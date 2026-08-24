from iris.config import settings

from .variant import Variant


class AskUserVariant(Variant):
    """Variant configuration for the AskUserPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        agent_model: str,
        guide_model: str | None = None,
        assessment_model: str | None = None,
        local_agent_model: str | None = None,
        local_guide_model: str | None = None,
        local_assessment_model: str | None = None,
    ):
        guide_model = guide_model or agent_model
        assessment_model = assessment_model or agent_model

        # Mirror resolve_model()'s deployment-wide kill switch: when local LLM
        # support is disabled outright, "local" must resolve to the cloud id
        # rather than silently falling back to a distinct local_*_model that
        # was only ever meant to be used when local LLMs are actually served.
        if settings.local_llm_enabled:
            local_agent_model = local_agent_model or agent_model
            local_guide_model = local_guide_model or guide_model
            local_assessment_model = local_assessment_model or assessment_model
        else:
            local_agent_model = agent_model
            local_guide_model = guide_model
            local_assessment_model = assessment_model

        role_models = {
            "chat": {
                "local": local_agent_model,
                "cloud": agent_model,
            },
            "guide": {
                "local": local_guide_model,
                "cloud": guide_model,
            },
            "assessment": {
                "local": local_assessment_model,
                "cloud": assessment_model,
            },
        }
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
            role_models=role_models,
            required_model_ids={
                local_agent_model,
                agent_model,
                local_guide_model,
                guide_model,
                local_assessment_model,
                assessment_model,
            },
        )
        self.agent_model = agent_model
        self.guide_model = guide_model
        self.assessment_model = assessment_model
