from .abstract_variant import AbstractVariant


class LectureIngestionUpdateVariant(AbstractVariant):
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        chat_model: str,
        embedding_model: str,
    ):
        super().__init__(
            id=id,
            name=name,
            description=description,
        )
        self.chat_model = chat_model
        self.embedding_model = embedding_model

    def required_models(self) -> set[str]:
        return {self.chat_model, self.embedding_model}