"""
Classifier using AI to classify prompts to keywords.
"""
import logging
from typing import List
from logos.classification.classifier import Classifier
from logos.classification.laura_embedding_classifier import LauraEmbeddingClassifier


class AIClassifier(Classifier):
    def __init__(self, models: List[dict]) -> None:
        super().__init__(models)
        self.ids = {i["id"] for i in models}

    def classify(self, prompt: str, _: dict, *args, **kwargs) -> List:
        laura: LauraEmbeddingClassifier = kwargs["laura"]
        for model in self.models:
            if model["id"] not in laura.model_db:
                laura.register_model(model["id"], model["description"])
        ranking = laura.classify_prompt(prompt, top_k=len(laura.model_db))
        ranking = {idx: value for (idx, value) in ranking}
        for model in self.models:
            model["classification_weight"].add_weight(ranking[model["id"]])
            print(f"Laura weight for model {model['id']} is: {ranking[model["id"]]}")
        return self.models
