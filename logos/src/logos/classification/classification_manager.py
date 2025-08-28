"""
Module handling all classification tasks in Logos.
"""
import functools
import logging
from copy import deepcopy
from typing import List, Tuple

from logos.classification.classify_policy import PolicyClassifier
from logos.classification.classify_token import TokenClassifier
from logos.classification.classify_ai import AIClassifier
from logos.classification.laura_embedding_classifier import LauraEmbeddingClassifier


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
        self.laura.remove_db()
        self.filtered = models  # For debugging
        if not self.laura.model_db:
            for model in self.models:
                if model["description"] is not None:
                    self.laura.register_model(model["id"], model["description"])

    def update_manager(self, models):
        self.models = models
        for model in self.models:
            if model["description"] is not None:
                self.laura.register_model(model["id"], model["description"])

    def classify(self, prompt: str, policy: dict, allowed=None, classifier=None, system=None) -> List[Tuple[int, int, int, int]]:
        """
        Classify prompts and assign them to a model.
        Returns a sorted list with the best suited model-id at the front together with
        a weight describing how well the LLM is suited for the given prompt
        and a priority of the given policy.
        """
        if allowed is None:
            allowed = list()
        else:
            self.models = [model for model in self.models if model["id"] in allowed]
        if system is None:
            system = ""
        adjusted_policy = deepcopy(policy)
        if adjusted_policy["threshold_latency"] == 1024:
            adjusted_policy["threshold_latency"] = self.get_special_weight("weight_latency", allowed=allowed)
        elif adjusted_policy["threshold_latency"] == -1024:
            adjusted_policy["threshold_latency"] = self.get_special_weight("weight_latency", maximum=False, allowed=allowed)
        if adjusted_policy["threshold_accuracy"] == 1024:
            adjusted_policy["threshold_accuracy"] = self.get_special_weight("weight_accuracy", allowed=allowed)
        elif adjusted_policy["threshold_accuracy"] == -1024:
            adjusted_policy["threshold_accuracy"] = self.get_special_weight("weight_accuracy", maximum=False, allowed=allowed)
        if adjusted_policy["threshold_cost"] == 1024:
            adjusted_policy["threshold_cost"] = self.get_special_weight("weight_cost", allowed=allowed)
        elif adjusted_policy["threshold_cost"] == -1024:
            adjusted_policy["threshold_cost"] = self.get_special_weight("weight_cost", maximum=False, allowed=allowed)
        if adjusted_policy["threshold_quality"] == 1024:
            adjusted_policy["threshold_quality"] = self.get_special_weight("weight_quality", allowed=allowed)
        elif adjusted_policy["threshold_quality"] == -1024:
            adjusted_policy["threshold_quality"] = self.get_special_weight("weight_quality", maximum=False, allowed=allowed)
        logging.debug(f"Policy: {adjusted_policy['id']}")
        logging.debug(f"Models: {allowed}")
        if classifier is None or classifier == "policy":
            filtered = PolicyClassifier(self.models).classify(prompt, adjusted_policy)
        else:
            filtered = [i for i in self.models]
        logging.debug(f"Policy-Classification: {[model['id'] for model in filtered]}")
        if classifier is None or classifier == "token":
            # Provide the system prompt instead of the normal user input
            filtered = TokenClassifier(filtered).classify(system, adjusted_policy)
        logging.debug(f"Token-Classification: {[model['id'] for model in filtered]}")
        self.laura.allowed = allowed
        if classifier is None or classifier == "laura":
            filtered = AIClassifier(filtered).classify(prompt, adjusted_policy, laura=self.laura)
        logging.debug(f"AI-Classification: {[model['id'] for model in filtered]}")
        self.laura.allowed = list()
        self.filtered = filtered
        return sorted(
            [(i["id"], i["classification_weight"].get_weight(), adjusted_policy["priority"], i["parallel"]) for i in filtered],
            key=lambda x: x[1], reverse=True)

    def calc_weight(self, model):
        """
        Calculates a combined weight over all weights of an LLM.
        """
        return self.WEIGHT_ACCURACY * model["weight_accuracy"] + \
            self.WEIGHT_COST * model["weight_cost"] + \
            self.WEIGHT_LATENCY * model["weight_latency"] + \
            self.WEIGHT_QUALITY * model["weight_quality"]

    def get_special_weight(self, category: str, maximum=True, allowed=None):
        weight = -1e10 if maximum else 1e10
        found = False
        for model in self.models:
            if (not allowed or model["id"] in allowed) and ((model[category] > weight and maximum) or (model[category] < weight and not maximum)):
                weight = model[category]
                found = True
        if not found:
            return 0
        return weight
