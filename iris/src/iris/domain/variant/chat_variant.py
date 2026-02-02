from typing import Optional

from .abstract_variant import AbstractAgentVariant


class ChatVariant(AbstractAgentVariant):
    """Variant configuration for the ChatPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        agent_model: str,
        citation_model: Optional[str] = None,
    ):
        super().__init__(
            variant_id=variant_id,
            name=name,
            description=description,
            agent_model=agent_model,
        )
        self.citation_model = citation_model  # TODO: Check if needed

    def required_models(self) -> set[str]:
        models = {self.agent_model}
        if self.citation_model:
            models.add(self.citation_model)
        return models
