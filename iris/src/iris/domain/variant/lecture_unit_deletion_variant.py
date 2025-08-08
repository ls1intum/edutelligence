from .abstract_variant import AbstractVariant


class LectureUnitDeletionVariant(AbstractVariant):
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
    ):
        super().__init__(
            id=id,
            name=name,
            description=description,
        )

    def required_models(self) -> set[str]:
        return set()  # No models required for deletion operations