"""
Classifier using keywords in prompts.
"""
import logging
from typing import List
from logos.classification.classifier import Classifier


class TokenClassifier(Classifier):
    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, prompt: str, _: dict, *args, **kwargs) -> List:
        for model in self.models:
            tags = model["tags"].split(";")
            matches = sum(1 for tag in tags if tag.lower() in prompt.lower())
            score = matches / len(tags)
            model["classification_weight"] += score
            print(f"Token weight for model {model['id']} is: {score}")
        return self.models
