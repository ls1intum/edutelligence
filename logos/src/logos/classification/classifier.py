"""
Base classifier for prompts.
"""
from abc import ABC, abstractmethod
from typing import List, Dict


class Classifier(ABC):
    def __init__(self, models: List[dict]) -> None:
        self.models = models

    @abstractmethod
    def classify(self, prompt: str, policy: dict) -> List[Dict]:
        """Return the subset of `self.models` matching the prompt/policy."""
