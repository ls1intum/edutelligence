"""
Classifier using keywords in prompts.
"""
from typing import List
from logos.classification.classifier import Classifier


class TokenClassifier(Classifier):
    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, prompt: str, _: dict) -> List:
        # TODO: call token classification procedure to rank/filter models
        return self.models
