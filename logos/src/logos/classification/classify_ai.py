"""
Classifier using AI to classify prompts to keywords.
"""
from typing import List
from logos.classification.classifier import Classifier


class AIClassifier(Classifier):
    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, prompt: str, _: dict) -> List:
        # TODO: call AI service to rank/filter models
        return self.models
