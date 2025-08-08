from .abstract_variant import AbstractAgentVariant


class ChatGPTWrapperVariant(AbstractAgentVariant):
    """Variant configuration for the ChatGPTWrapperPipeline."""

    def __init__(
        self,
        variant_id: str,
        name: str,
        description: str,
        agent_model: str,
    ):
        super().__init__(
            id=variant_id,
            name=name,
            description=description,
            agent_model=agent_model,
        )

    def required_models(self) -> set[str]:
        return {self.agent_model}
