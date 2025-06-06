"""
Base classifier for prompts.
"""
from typing import List


class Classifier:
    def __init__(self, models: List[dict]) -> None:
        self.models = models

    def classify(self, prompt: str, policy: dict) -> List:
        raise NotImplementedError("Classify must be overridden by classifiers")
