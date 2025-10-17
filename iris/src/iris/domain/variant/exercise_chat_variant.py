from .abstract_variant import AbstractAgentVariant
from ...cloud_context import localModelString, isCloudEnabled


class ExerciseChatVariant(AbstractAgentVariant):
    """Variant configuration for the ExerciseChatPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        agent_model: str,
        citation_model: str,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
            agent_model=agent_model,
        )
        self.citation_model = citation_model if isCloudEnabled.get() else localModelString

    def required_models(self) -> set[str]:
        return {self.agent_model, self.citation_model}
