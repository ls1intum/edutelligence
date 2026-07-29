from .variant import Variant


class PromptUserVariant(Variant):
    """Variant configuration for the PromptUserPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        agent_model: str,
        guide_model: str | None = None,
        local_agent_model: str | None = None,
        local_guide_model: str | None = None,
    ):
        guide_model = guide_model or agent_model
        local_agent_model = local_agent_model or agent_model
        local_guide_model = local_guide_model or guide_model
        role_models = {
            "chat": {
                "local": local_agent_model,
                "cloud": agent_model,
            },
            "guide": {
                "local": local_guide_model,
                "cloud": guide_model,
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
            },
        )
        self.agent_model = agent_model
        self.guide_model = guide_model
