"""
Module filtering available LLMs by a given policy.
"""
from copy import deepcopy
from typing import List

from classifier import Classifier


class PolicyClassifier(Classifier):
    privacy = [
        "LOCAL",
        "CLOUD_IN_EU_BY_EU_PROVIDER",
        "CLOUD_IN_EU_BY_US_PROVIDER",
        "CLOUD_NOT_IN_EU_BY_US_PROVIDER"
    ]

    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)

    def classify(self, _: str, policy: dict) -> List:
        models = deepcopy(self.models)
        # Privacy
        privacy = lambda x: self.privacy.index(policy["threshold_privacy"]) >= self.privacy.index(x["weight_privacy"])
        models = [i for i in models if privacy(i)]
        # Cost: The higher the value the cheaper
        cost = lambda x: policy["threshold_cost"] <= x["weight_cost"]
        models = [i for i in models if cost(i)]
        # Latency: The higher the value the shorter the response time per token
        latency = lambda x: policy["threshold_latency"] <= x["weight_latency"]
        models = [i for i in models if latency(i)]
        # Accuracy: The higher the value the better the result accuracy
        accuracy = lambda x: policy["threshold_accuracy"] <= x["weight_accuracy"]
        models = [i for i in models if accuracy(i)]
        # Quality: The higher the value the higher the result quality
        quality = lambda x: policy["threshold_quality"] <= x["weight_quality"]
        models = [i for i in models if quality(i)]
        return models
