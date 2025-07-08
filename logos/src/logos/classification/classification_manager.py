"""
Module handling all classification tasks in Logos.
"""
import functools
from typing import List, Tuple

from logos.classification.classify_policy import PolicyClassifier
from logos.classification.classify_token import TokenClassifier
from logos.classification.classify_ai import AIClassifier
from logos.classification.laura_embedding_classifier import LauraEmbeddingClassifier
from logos.dbutils.dbmanager import DBManager


def singleton(cls):
    """
    A decorator to make a class a Singleton.
    """
    instances = {}

    @functools.wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


@singleton
class ClassificationManager:
    WEIGHT_ACCURACY = 1.3
    WEIGHT_COST = 1.5
    WEIGHT_LATENCY = 1.1
    WEIGHT_QUALITY = 1.1

    def __init__(self, models) -> None:
        self.models = models
        self.laura = LauraEmbeddingClassifier()
        self.filtered = models  # For debugging
        if not self.laura.model_db:
            for model in self.models:
                self.laura.register_model(model["id"], model["description"])

    def update_manager(self, models):
        self.models = models
        for model in self.models:
            self.laura.register_model(model["id"], model["description"])

    def classify(self, prompt: str, policy: dict, allowed=None) -> List[Tuple[int, int, int, int]]:
        """
        Classify prompts and assign them to a model.
        Returns a sorted list with the best suited model-id at the front together with
        a weight describing how well the LLM is suited for the given prompt
        and a priority of the given policy.
        """
        if allowed is None:
            allowed = list()
        filtered = PolicyClassifier(self.models).classify(prompt, policy)
        filtered = TokenClassifier(filtered).classify(prompt, policy)
        self.laura.allowed = allowed
        filtered = AIClassifier(filtered).classify(prompt, policy, laura=self.laura)
        self.laura.allowed = list()
        self.filtered = filtered
        return sorted(
            [(i["id"], i["classification_weight"].get_weight(), policy["priority"], i["parallel"]) for i in filtered],
            key=lambda x: x[1], reverse=True)

    def calc_weight(self, model):
        """
        Calculates a combined weight over all weights of an LLM.
        """
        return self.WEIGHT_ACCURACY * model["weight_accuracy"] + \
            self.WEIGHT_COST * model["weight_cost"] + \
            self.WEIGHT_LATENCY * model["weight_latency"] + \
            self.WEIGHT_QUALITY * model["weight_quality"]
