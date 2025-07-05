"""
Classifier using keywords in prompts.
"""
import math
from typing import List
from logos.classification.classifier import Classifier


def weighted_average(relative, absolut, tau=4):
    return relative * (1 - math.exp(-absolut/tau))


class TokenClassifier(Classifier):
    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, prompt: str, _: dict, *args, **kwargs) -> List:
        for model in self.models:
            tags = model["tags"].split(";")
            matches = sum(1 for tag in tags if tag.lower() in prompt.lower())
            relative = matches / len(tags)
            absolute = matches
            score = weighted_average(relative, absolute)
            model["classification_weight"].add_weight(score, "token")
            print(f"Token weight for model {model['id']} is: {score}")
        return self.models
