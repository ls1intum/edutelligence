"""
Classifier using keywords in prompts.
"""
from typing import List
from classifier import Classifier


class TokenClassifier(Classifier):
    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, prompt: str, _: dict) -> List:
        return self.models
