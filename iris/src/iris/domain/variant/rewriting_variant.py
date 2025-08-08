from .abstract_variant import AbstractVariant


class RewritingVariant(AbstractVariant):
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        rewriting_model: str,
        consistency_model: str = None,
    ):
        super().__init__(
            id=id,
            name=name,
            description=description,
        )
        self.rewriting_model = rewriting_model
        self.consistency_model = consistency_model or rewriting_model

    def required_models(self) -> set[str]:
        models = {self.rewriting_model}
        if self.consistency_model != self.rewriting_model:
            models.add(self.consistency_model)
        return models