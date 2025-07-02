"""
Module filtering available LLMs by a given policy.
"""
import logging
from copy import deepcopy
from typing import List
import math

from logos.classification.classifier import Classifier

def sigmoid(x, t, k=0.2):
    return 1 / (1 + math.pow(math.e, -k*(x-t)))


class PolicyClassifier(Classifier):
    privacy = [
        "LOCAL",
        "CLOUD_IN_EU_BY_EU_PROVIDER",
        "CLOUD_IN_EU_BY_US_PROVIDER",
        "CLOUD_NOT_IN_EU_BY_US_PROVIDER"
    ]

    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, _: str, policy: dict, strict=False, *args, **kwargs) -> List:
        models = deepcopy(self.models)

        # Hard Filtering
        # Privacy
        privacy = lambda x: self.privacy.index(policy["threshold_privacy"]) >= self.privacy.index(x["weight_privacy"])
        models = [i for i in models if privacy(i)]
        # Cost: The higher the value the cheaper
        cost = lambda x: policy["threshold_cost"] <= x["weight_cost"]
        models = [i for i in models if cost(i)]

        # Soft Filtering
        # Latency: The higher the value the shorter the response time per token
        for model in models:
            if not strict or policy["threshold_latency"] <= model["weight_latency"]:
                weight = sigmoid(model["weight_latency"], policy["threshold_latency"])
            else:
                weight = 0
            print(f"Latency weight for model {model['id']} is: {weight}")
            model["classification_weight"] += weight
        # Accuracy: The higher the value the better the result accuracy
        for model in models:
            if not strict or policy["threshold_accuracy"] <= model["weight_accuracy"]:
                weight = sigmoid(model["weight_accuracy"], policy["threshold_accuracy"])
            else:
                weight = 0
            model["classification_weight"] += weight
            print(f"Accuracy weight for model {model['id']} is: {weight}")
        # Quality: The higher the value the higher the result quality
        for model in models:
            if not strict or policy["threshold_quality"] <= model["weight_quality"]:
                weight = sigmoid(model["weight_quality"], policy["threshold_quality"])
            else:
                weight = 0
            model["classification_weight"] += weight
            print(f"Quality weight for model {model['id']} is: {weight}")
        return models
