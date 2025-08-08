from .abstract_variant import AbstractAgentVariant


class ExerciseChatVariant(AbstractAgentVariant):
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        agent_model: str,
        citation_model: str,
    ):
        super().__init__(
            id=id,
            name=name,
            description=description,
            agent_model=agent_model,
        )
        self.citation_model = citation_model

    def required_models(self) -> set[str]:
        return {self.agent_model, self.citation_model}